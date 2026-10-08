"""Rehearse current migrations against synthetic legacy and corrupted SQLite data.

The rehearsal never opens the configured application database. It creates isolated
database files, applies the current migration chain twice, and emits a sanitized
JSON reconciliation report suitable for contest release checks.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session


PROJECT_ROOT = Path(__file__).resolve().parent.parent
BACKEND_DIR = PROJECT_ROOT / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app.db.database import (  # noqa: E402
    _migrate_sqlite_feedback_records,
    _migrate_sqlite_generated_resources,
    _migrate_sqlite_generation_jobs,
    configure_sqlite_foreign_keys,
)
from app.db.integrity import inspect_database_integrity  # noqa: E402
from app.db.migrations import (  # noqa: E402
    apply_p0_04_migration,
    apply_p0_05_migration,
    apply_p0_06_migration,
    apply_p0_07_feedback_migration,
    apply_p0_07_migration,
    apply_p0_09_migration,
)
from app.db.models import Base  # noqa: E402


DEFAULT_BASELINE_REF = "2c9dcbb"
CORE_LEGACY_TABLES = (
    "agent_runs",
    "agent_steps",
    "generated_resources",
    "resource_reviews",
    "resource_claims",
    "feedback_records",
    "learner_profiles",
    "knowledge_states",
)
FACT_TABLES_THAT_MUST_NOT_BE_INVENTED = (
    "workflow_events",
    "claim_judgements",
    "claim_evidence",
    "learning_attempts",
    "learning_attempt_point_results",
    "feedback_decisions",
    "knowledge_state_mutations",
    "learner_profile_versions",
    "learning_path_mutations",
    "feedback_followup_runs",
)


def _legacy_namespace(baseline_ref: str) -> dict[str, Any]:
    result = subprocess.run(
        ["git", "show", f"{baseline_ref}:backend/app/db/models.py"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    namespace: dict[str, Any] = {"__name__": "synthetic_legacy_models"}
    exec(compile(result.stdout, f"{baseline_ref}:models.py", "exec"), namespace)
    return namespace


def _seed_legacy_database(path: Path, baseline_ref: str, scenario: str) -> None:
    namespace = _legacy_namespace(baseline_ref)
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    namespace["Base"].metadata.create_all(engine)

    with Session(engine) as db:
        db.add(namespace["KnowledgeBaseORM"](
            knowledge_base_id="kb-legacy",
            name="Synthetic legacy RAG knowledge base",
            version="0.5.0",
            domain="RAG",
        ))
        db.add(namespace["LearnerProfileORM"](
            learner_id="legacy-learner",
            learner_type="student",
            education="undergraduate",
            major="software engineering",
            knowledge_base_id="kb-legacy",
            learning_goal="learn RAG",
            knowledge_states={"skill-retrieval": {"score": 0.35}},
        ))
        db.add(namespace["RagSkillNodeORM"](
            node_id="skill-retrieval",
            knowledge_base_id="kb-legacy",
            name="Retrieval",
            level="beginner",
        ))
        db.add(namespace["KnowledgeStateORM"](
            state_id="state-legacy",
            learner_id="legacy-learner",
            knowledge_base_id="kb-legacy",
            skill_node_id="skill-retrieval",
            mastery_score=0.35,
            status="learning",
        ))
        db.add(namespace["AgentRunORM"](
            run_id="legacy-run",
            learner_id="legacy-learner",
            knowledge_base_id="kb-legacy",
            topic="retrieval",
            status="completed",
            workflow_status="completed",
            execution_status="completed",
            replay_completeness="legacy_partial",
        ))
        db.add(namespace["AgentStepORM"](
            step_id="legacy-step",
            run_id="legacy-run",
            step_no=1,
            agent_name="GeneratorAgent",
            node_name="generator",
            action="generate",
            status="success",
        ))
        first_resource = namespace["GeneratedResourceORM"](
            resource_id="legacy-resource-v1",
            run_id="legacy-run",
            generation_step_id="legacy-step",
            learner_id="legacy-learner",
            topic="retrieval",
            resource_type="讲义",
            difficulty="初级",
            storage_type="text",
            content_text="Legacy retrieval lesson version 1",
            review_status="approved",
            review_id="legacy-review",
            publication_status="unpublished",
            version=1,
        )
        second_resource = namespace["GeneratedResourceORM"](
            resource_id="legacy-resource-v2",
            run_id="legacy-run",
            generation_step_id="legacy-step",
            learner_id="legacy-learner",
            topic="retrieval",
            resource_type="讲义",
            difficulty="初级",
            storage_type="text",
            content_text="Legacy retrieval lesson version 2",
            review_status="approved",
            publication_status="unpublished",
            version=2,
            parent_resource_id="legacy-resource-v1",
        )
        db.add_all([first_resource, second_resource])
        db.add(namespace["ResourceReviewORM"](
            review_id="legacy-review",
            resource_id="legacy-resource-v1",
            run_id="legacy-run",
            status="approved",
        ))
        db.add(namespace["ResourceClaimORM"](
            claim_id="legacy-claim",
            review_id="legacy-review",
            resource_id="legacy-resource-v1",
            knowledge_point="retrieval",
            claim_text="A legacy claim without modern judgement evidence.",
            supported=True,
        ))
        db.add(namespace["FeedbackRecordORM"](
            feedback_id="legacy-feedback",
            learner_id="legacy-learner",
            resource_id="legacy-resource-v1",
            correct_rate=0.4,
            decision="regenerate",
        ))
        if scenario == "duplicate":
            db.add(namespace["GeneratedResourceORM"](
                resource_id="duplicate-resource-v1",
                run_id="legacy-run",
                generation_step_id="legacy-step",
                learner_id="legacy-learner",
                topic="retrieval",
                resource_type="讲义",
                difficulty="初级",
                storage_type="text",
                content_text="Conflicting legacy version",
                publication_status="unpublished",
                version=1,
            ))
        db.commit()

    if scenario == "orphan":
        with engine.begin() as connection:
            connection.execute(text(
                "UPDATE generated_resources SET run_id='missing-run' "
                "WHERE resource_id='legacy-resource-v2'"
            ))
    engine.dispose()


def _snapshot(engine) -> dict[str, Any]:
    inspector = inspect(engine)
    tables = sorted(inspector.get_table_names())
    row_counts: dict[str, int] = {}
    with engine.connect() as connection:
        for table in tables:
            row_counts[table] = int(
                connection.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar_one()
            )
        migration_ids = (
            sorted(row[0] for row in connection.execute(text(
                "SELECT migration_id FROM schema_migrations ORDER BY migration_id"
            )).fetchall())
            if "schema_migrations" in tables
            else []
        )
        resource_rows = (
            [dict(row._mapping) for row in connection.execute(text(
                "SELECT resource_id, run_id, resource_type, version, parent_resource_id, "
                "review_status, publication_status FROM generated_resources "
                "ORDER BY resource_id"
            )).fetchall()]
            if "generated_resources" in tables
            else []
        )
        legacy_partial_count = (
            int(connection.execute(text(
                "SELECT COUNT(*) FROM agent_runs WHERE replay_completeness='legacy_partial'"
            )).scalar_one())
            if "agent_runs" in tables
            and "replay_completeness" in {item["name"] for item in inspector.get_columns("agent_runs")}
            else 0
        )
        unpublished_resource_count = (
            int(connection.execute(text(
                "SELECT COUNT(*) FROM generated_resources "
                "WHERE publication_status='unpublished'"
            )).scalar_one())
            if "generated_resources" in tables
            and "publication_status" in {
                item["name"] for item in inspector.get_columns("generated_resources")
            }
            else 0
        )
        if "resource_claims" in tables and "claim_judgements" in tables:
            legacy_unavailable_claim_count = int(connection.execute(text(
                "SELECT COUNT(*) FROM resource_claims AS claim "
                "LEFT JOIN claim_judgements AS judgement "
                "ON judgement.claim_id = claim.claim_id "
                "WHERE judgement.claim_id IS NULL"
            )).scalar_one())
        else:
            legacy_unavailable_claim_count = row_counts.get("resource_claims", 0)
        invalid_status_count = 0
        if "generated_resources" in tables and "publication_status" in {
            item["name"] for item in inspector.get_columns("generated_resources")
        }:
            invalid_status_count += int(connection.execute(text(
                "SELECT COUNT(*) FROM generated_resources "
                "WHERE publication_status NOT IN ('unpublished', 'published')"
            )).scalar_one())
        if "generation_jobs" in tables:
            invalid_status_count += int(connection.execute(text(
                "SELECT COUNT(*) FROM generation_jobs "
                "WHERE status NOT IN ('queued', 'running', 'completed', 'failed', 'interrupted')"
            )).scalar_one())
    return {
        "table_count": len(tables),
        "migration_ids": migration_ids,
        "row_counts": row_counts,
        "resources": resource_rows,
        "legacy_partial_count": legacy_partial_count,
        "legacy_unavailable_claim_count": legacy_unavailable_claim_count,
        "unpublished_resource_count": unpublished_resource_count,
        "invalid_status_count": invalid_status_count,
    }


def _apply_current_migrations(path: Path) -> Any:
    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{path.as_posix()}")
    )
    Base.metadata.create_all(engine)
    apply_p0_04_migration(engine)
    apply_p0_05_migration(engine)
    apply_p0_06_migration(engine)
    apply_p0_07_migration(engine)
    apply_p0_07_feedback_migration(engine)
    _migrate_sqlite_generated_resources(engine)
    _migrate_sqlite_generation_jobs(engine)
    _migrate_sqlite_feedback_records(engine)
    apply_p0_09_migration(engine)
    return engine


def _verify_database_unique_guard(engine) -> bool:
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO generated_resources "
                "(resource_id, run_id, generation_step_id, learner_id, topic, "
                "resource_type, difficulty, storage_type, publication_status, version) "
                "VALUES ('post-migration-duplicate', 'legacy-run', 'legacy-step', "
                "'legacy-learner', 'retrieval', '讲义', '初级', 'text', "
                "'unpublished', 1)"
            ))
    except IntegrityError:
        return True
    return False


def _run_clean_rehearsal(path: Path, baseline_ref: str) -> dict[str, Any]:
    _seed_legacy_database(path, baseline_ref, "clean")
    pre_engine = create_engine(f"sqlite:///{path.as_posix()}")
    before = _snapshot(pre_engine)
    pre_engine.dispose()

    first_engine = _apply_current_migrations(path)
    after_first = _snapshot(first_engine)
    first_integrity = inspect_database_integrity(first_engine)
    unique_guard_enforced = _verify_database_unique_guard(first_engine)
    first_engine.dispose()

    second_engine = _apply_current_migrations(path)
    after_second = _snapshot(second_engine)
    second_integrity = inspect_database_integrity(second_engine)
    second_engine.dispose()

    preserved_counts = {
        table: before["row_counts"].get(table, 0) == after_second["row_counts"].get(table, 0)
        for table in CORE_LEGACY_TABLES
    }
    no_invented_facts = {
        table: after_second["row_counts"].get(table, 0) == 0
        for table in FACT_TABLES_THAT_MUST_NOT_BE_INVENTED
    }
    resource_status_preserved = all(
        item["publication_status"] == "unpublished"
        for item in after_second["resources"]
        if item["resource_id"].startswith("legacy-resource")
    )
    assertions = {
        "legacy_row_counts_preserved": all(preserved_counts.values()),
        "migration_second_run_idempotent": (
            after_first["migration_ids"] == after_second["migration_ids"]
            and after_first["row_counts"] == after_second["row_counts"]
        ),
        "no_historical_facts_invented": all(no_invented_facts.values()),
        "approved_legacy_resources_remain_unpublished": resource_status_preserved,
        "legacy_run_remains_partial": after_second["legacy_partial_count"] == 1,
        "legacy_claim_remains_unavailable": (
            after_second["legacy_unavailable_claim_count"] == 1
        ),
        "resource_unique_guard_enforced": unique_guard_enforced,
        "foreign_keys_enabled": second_integrity["foreign_keys_enabled"] is True,
        "foreign_key_check_clean": not second_integrity["foreign_key_violations"],
        "resource_foreign_keys_complete": not second_integrity["missing_resource_foreign_keys"],
        "resource_duplicate_check_clean": not second_integrity["resource_version_duplicates"],
    }
    return {
        "database": str(path),
        "before": before,
        "after_first_migration": after_first,
        "after_second_migration": after_second,
        "preserved_counts": preserved_counts,
        "no_invented_fact_counts": no_invented_facts,
        "integrity": second_integrity,
        "assertions": assertions,
        "status": "passed" if all(assertions.values()) else "failed",
    }


def _run_failure_rehearsal(path: Path, baseline_ref: str, scenario: str) -> dict[str, Any]:
    _seed_legacy_database(path, baseline_ref, scenario)
    pre_engine = create_engine(f"sqlite:///{path.as_posix()}")
    before = _snapshot(pre_engine)
    pre_engine.dispose()
    error_type = None
    error_message = None
    try:
        engine = _apply_current_migrations(path)
    except Exception as exc:  # expected fail-closed result is recorded below
        error_type = type(exc).__name__
        error_message = str(exc)
    else:
        engine.dispose()

    post_engine = create_engine(f"sqlite:///{path.as_posix()}")
    after = _snapshot(post_engine)
    post_engine.dispose()
    expected_error = (
        "RESOURCE_VERSION_DUPLICATES" if scenario == "duplicate" else "FOREIGN_KEY_VIOLATIONS"
    )
    core_rows_preserved = all(
        before["row_counts"].get(table, 0) == after["row_counts"].get(table, 0)
        for table in CORE_LEGACY_TABLES
    )
    passed = bool(error_message and expected_error in error_message and core_rows_preserved)
    return {
        "database": str(path),
        "scenario": scenario,
        "error_type": error_type,
        "error_message": error_message,
        "expected_error": expected_error,
        "core_legacy_rows_preserved": core_rows_preserved,
        "status": "passed" if passed else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline-ref", default=DEFAULT_BASELINE_REF)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    output_dir = args.output_dir or Path(tempfile.mkdtemp(prefix="xh-db-rehearsal-"))
    output_dir.mkdir(parents=True, exist_ok=True)
    clean_path = output_dir / "synthetic-legacy-clean.db"
    duplicate_path = output_dir / "synthetic-legacy-duplicate.db"
    orphan_path = output_dir / "synthetic-legacy-orphan.db"
    for path in (clean_path, duplicate_path, orphan_path):
        if path.exists():
            path.unlink()

    report = {
        "rehearsal_type": "synthetic_legacy_sqlite",
        "baseline_ref": args.baseline_ref,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "output_dir": str(output_dir),
        "configured_application_database_touched": False,
        "clean_upgrade": _run_clean_rehearsal(clean_path, args.baseline_ref),
        "failure_cases": {
            "duplicate_resource_version": _run_failure_rehearsal(
                duplicate_path, args.baseline_ref, "duplicate"
            ),
            "orphan_resource_reference": _run_failure_rehearsal(
                orphan_path, args.baseline_ref, "orphan"
            ),
        },
    }
    report["status"] = (
        "passed"
        if report["clean_upgrade"]["status"] == "passed"
        and all(item["status"] == "passed" for item in report["failure_cases"].values())
        else "failed"
    )
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
