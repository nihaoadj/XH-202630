"""Read-only, sanitized P0-09 demo preflight.

Exit codes: 0 READY, 2 DEGRADED, 1 NOT_READY.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import inspect, text


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
LATEST_MIGRATIONS = {
    "20260730_p0_04_agent_run_persistence",
    "20260807_p0_05_generation_review_revision",
    "20260809_p0_06_claim_evidence_audit",
    "20260810_p0_07_runtime_observability",
    "20260811_p0_07_feedback_profile_path_closed_loop",
    "20260815_p0_09_database_integrity",
    "20260819_tutor_sessions_turns",
    "20260819_p0_10_assessment_question_catalog",
    "20260819_p0_11_resource_batches",
    "20260819_p0_12_superseded_generation_jobs",
}


def _check_database(engine) -> dict:
    result = {
        "status": "ready",
        "backend": engine.url.get_backend_name(),
        "reachable": False,
        "migration_latest": False,
        "foreign_keys_enforced": None,
        "resource_version_unique": False,
        "error_codes": [],
    }
    try:
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        result["reachable"] = True
        applied: set[str] = set()
        if "schema_migrations" in tables:
            with engine.connect() as connection:
                applied = {
                    str(row[0])
                    for row in connection.execute(text("SELECT migration_id FROM schema_migrations"))
                }
                if result["backend"] == "sqlite":
                    result["foreign_keys_enforced"] = bool(
                        connection.execute(text("PRAGMA foreign_keys")).scalar()
                    )
        result["migration_latest"] = LATEST_MIGRATIONS <= applied
        if not result["migration_latest"]:
            result["error_codes"].append("P0_09_MIGRATION_NOT_LATEST")
        if result["backend"] == "sqlite" and not result["foreign_keys_enforced"]:
            result["error_codes"].append("P0_09_SQLITE_FOREIGN_KEYS_DISABLED")
        if "generated_resources" in tables:
            wanted = ["run_id", "resource_type", "version"]
            constraints = inspector.get_unique_constraints("generated_resources")
            indexes = inspector.get_indexes("generated_resources")
            result["resource_version_unique"] = any(
                item.get("column_names") == wanted
                for item in [*constraints, *[index for index in indexes if index.get("unique")]]
            )
        if not result["resource_version_unique"]:
            result["error_codes"].append("P0_09_RESOURCE_VERSION_UNIQUE_MISSING")
    except Exception:
        result["status"] = "not_ready"
        result["error_codes"].append("P0_09_DATABASE_UNREACHABLE")
        return result
    if result["error_codes"]:
        result["status"] = "degraded"
    return result


def _check_retrieval_smoke(settings) -> dict:
    """Run one local, read-only default-KB query and expose counts only."""

    from app.core.knowledge_base import load_knowledge_base_manifest
    from app.core.vector_store import similarity_search

    result = {
        "status": "not_ready",
        "knowledge_base_id": None,
        "hit_count": 0,
        "error_codes": [],
    }
    try:
        knowledge_base_id = str(
            load_knowledge_base_manifest(settings.knowledge_base_dir)["knowledge_base_id"]
        )
        hits = similarity_search(
            "检索增强生成的证据校验",
            top_k=1,
            knowledge_base_id=knowledge_base_id,
        )
        result["knowledge_base_id"] = knowledge_base_id
        result["hit_count"] = len(hits)
        result["status"] = "ready" if hits else "degraded"
        if not hits:
            result["error_codes"].append("P0_09_RETRIEVAL_NO_HIT")
    except Exception:
        result["status"] = "not_ready"
        result["error_codes"].append("P0_09_RETRIEVAL_SMOKE_FAILED")
    return result


def build_preflight() -> dict:
    sys.path.insert(0, str(BACKEND_DIR))
    from app.config import get_settings
    from app.core.health import build_health_report
    from app.db.database import get_engine

    settings = get_settings()
    health = build_health_report(settings)
    database = _check_database(get_engine())
    retrieval = _check_retrieval_smoke(settings)
    frontend_dist = PROJECT_ROOT / "frontend" / "dist" / "index.html"
    checks = {
        "health": health.model_dump(mode="json", exclude_none=True),
        "database": database,
        "retrieval_smoke": retrieval,
        "configuration": {
            "app_mode": settings.app_mode,
            "db_type": settings.db_type,
            "knowledge_base_dir_configured": bool(settings.knowledge_base_dir),
            "llm_configured": bool(settings.llm_api_key and settings.llm_model),
            "structured_output_mode": settings.llm_structured_output_mode,
            "degraded_generation_allowed": bool(
                settings.allow_degraded_generation and settings.app_mode != "production"
            ),
        },
        "frontend": {
            "status": "ready" if frontend_dist.is_file() else "degraded",
            "build_artifact_present": frontend_dist.is_file(),
        },
    }
    if (
        health.status == "not_ready"
        or database["status"] == "not_ready"
        or retrieval["status"] == "not_ready"
    ):
        status = "NOT_READY"
    elif (
        health.status == "degraded"
        or database["status"] == "degraded"
        or retrieval["status"] == "degraded"
        or not frontend_dist.is_file()
    ):
        status = "DEGRADED"
    else:
        status = "READY"
    return {"status": status, "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only P0-09 demo preflight")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = build_preflight()
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    print(encoded)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + "\n", encoding="utf-8")
    return {"READY": 0, "DEGRADED": 2, "NOT_READY": 1}[payload["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
