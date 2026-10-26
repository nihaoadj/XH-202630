"""Reproducible report read benchmark; synthetic, disposable SQLite only.

Run from the repository root. SQL counts are executed statements and ORM counts
are loaded objects, not physical database scans. No model or business DB access.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from pathlib import Path
import platform
import sys
import tempfile
from threading import Lock
import time
import tracemalloc
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert
from sqlalchemy.orm import sessionmaker

from app.api.reports import report as routes
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.diagnosis.sql_repository import SQLDiagnosisRepository
from app.db.feedback.sql_repository import SQLFeedbackRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learners.mastery import SQLMasteryRepository
from app.db.learners.curriculum import SQLCurriculumRepository
from app.db.learners.tier_progress import SQLTierProgressRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import (
    Base, LearnerProfileORM, KnowledgeBaseORM, AgentRunORM,
    GeneratedResourceORM, LearningAttemptORM, LearningAttemptPointResultORM,
    FeedbackDecisionORM, LearningPathORM, LearningPathMutationORM,
    LearnerProfileVersionORM, ResourceReviewORM, ResourceClaimORM,
    ClaimJudgementORM, GenerationJobORM,
)
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES
from app.services.knowledge.knowledge import KnowledgeService
from app.services.learners.mastery import MasteryService
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService

NOW = datetime(2026, 10, 23, 12, tzinfo=timezone.utc)
LEARNER = "synthetic-report-learner"
SEED_VERSION = "report-read-v1"


def seed_database(engine, size: int) -> str:
    """Seed complete formal history, 30 published resources and exact audits."""
    Base.metadata.create_all(engine)
    try:
        from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration
    except ImportError:
        pass  # The same benchmark also runs before this optimization exists.
    else:
        apply_p0_35_report_read_model_migration(engine)
    with engine.begin() as db:
        db.execute(insert(KnowledgeBaseORM), [{"knowledge_base_id": "benchmark", "name": "Synthetic", "version": "1"}])
        db.execute(insert(LearnerProfileORM), [{
            "learner_id": LEARNER, "learner_type": "test", "education": "本科",
            "major": "software", "learning_goal": "synthetic", "knowledge_base_id": "benchmark",
            "created_at": NOW - timedelta(days=60), "updated_at": NOW - timedelta(days=1),
        }])
        db.execute(insert(AgentRunORM), [{"run_id": f"run-{i}", "learner_id": LEARNER, "status": "completed", "started_at": NOW - timedelta(days=2)} for i in range(6)])
        db.execute(insert(GenerationJobORM), [{
            "run_id": f"run-{i}", "batch_id": f"batch-{i}", "learner_id": LEARNER,
            "knowledge_base_id": "benchmark", "topic": "Synthetic", "status": "completed",
            "request_payload": {}, "created_at": NOW - timedelta(days=3, minutes=i),
        } for i in range(6)])
        kinds = GENERAL_GENERATION_RESOURCE_TYPES
        resources = [{
            "resource_id": f"resource-{i:03}", "run_id": f"run-{i // 5}",
            "batch_id": f"batch-{i // 5}", "learner_id": LEARNER, "resource_type": kinds[i % 5],
            "topic": f"Synthetic {i}", "difficulty": "初级", "content_text": "Synthetic fact.",
            "publication_status": "published", "published_at": NOW - timedelta(days=2, minutes=i),
            "created_at": NOW - timedelta(days=3, minutes=i), "review_status": "approved",
            "review_id": f"review-{i}", "version": 1,
        } for i in range(30)]
        resources[25]["version"] = 2
        # Use uniform insert keys; a published child hides its older parent.
        for resource in resources:
            resource["parent_resource_id"] = "resource-000" if resource["resource_id"] == "resource-025" else None
        db.execute(insert(GeneratedResourceORM), resources)
        db.execute(insert(ResourceReviewORM), [{
            "review_id": f"review-{i}", "resource_id": f"resource-{i:03}", "run_id": f"run-{i // 5}",
            "status": "approved", "review_pass_rate": 1.0, "created_at": NOW - timedelta(days=2),
        } for i in range(30)])
        digest = hashlib.sha256(b"Synthetic fact.").hexdigest()
        db.execute(insert(ResourceClaimORM), [{
            "claim_id": f"clm_{i:032x}", "review_id": f"review-{i}", "resource_id": f"resource-{i:03}",
            "schema_version": "2.0", "run_id": f"run-{i // 5}", "resource_version": resources[i]["version"], "claim_index": 0,
            "claim_type": "factual", "claim_text": "Synthetic fact.", "source_text": "Synthetic fact.",
            "source_start": 0, "source_end": 15, "source_text_hash": digest,
            "extraction_method": "deterministic", "extractor_prompt_version": "bench-v1",
            "claim_hash": digest, "supported": True, "created_at": NOW - timedelta(days=2),
        } for i in range(30)])
        db.execute(insert(ClaimJudgementORM), [{
            "judgement_id": f"jdg_{i:032x}", "claim_id": f"clm_{i:032x}", "run_id": f"run-{i // 5}",
            "resource_id": f"resource-{i:03}", "resource_version": resources[i]["version"], "review_id": f"review-{i}",
            "status": "completed", "verdict": "supported", "reason": "synthetic benchmark",
            "judge_type": "deterministic", "judge_prompt_version": "bench-v1", "created_at": NOW - timedelta(days=2),
        } for i in range(30)])
        db.execute(insert(LearningPathORM), [{"path_id": "path", "learner_id": LEARNER, "version": size + 1, "created_at": NOW, "updated_at": NOW}])
        for start in range(0, size, 500):
            indices = range(start, min(start + 500, size))
            times = {i: NOW - timedelta(minutes=i + 1) for i in indices}
            db.execute(insert(LearningAttemptORM), [{
                "attempt_id": f"attempt-{i:06}", "learner_id": LEARNER, "source_resource_id": "resource-000",
                "source_resource_version": 1, "idempotency_key": f"attempt-{i}", "request_hash": digest,
                "expected_profile_version": i + 1, "overall_score": 0.5, "submitted_at": times[i],
                "created_at": times[i], "metadata": {"total_score": 1.0, "max_score": 2.0},
            } for i in indices])
            db.execute(insert(LearningAttemptPointResultORM), [{
                "result_id": f"point-{i}", "attempt_id": f"attempt-{i:06}", "knowledge_point_id": "skill",
                "correct_count": 1, "total_count": 2, "score": 0.5, "question_ids": ["synthetic-question"],
            } for i in indices])
            db.execute(insert(FeedbackDecisionORM), [{
                "decision_id": f"decision-{i}", "learner_id": LEARNER, "attempt_id": f"attempt-{i:06}",
                "action": "hold", "reason_codes": ["SYNTHETIC"], "decision_reason": "Synthetic", "decision_hash": digest, "created_at": times[i],
            } for i in indices])
            db.execute(insert(LearningPathMutationORM), [{
                "mutation_id": f"mutation-{i}", "learner_id": LEARNER, "path_id": "path", "attempt_id": f"attempt-{i:06}",
                "decision_id": f"decision-{i}", "mutation_type": "hold", "path_version_before": i + 1,
                "path_version_after": i + 2, "created_at": times[i],
            } for i in indices])
            db.execute(insert(LearnerProfileVersionORM), [{
                "version_id": f"version-{i}", "learner_id": LEARNER, "profile_version": i + 2,
                "source_attempt_id": f"attempt-{i:06}", "source_decision_id": f"decision-{i}", "created_at": times[i],
            } for i in indices])
    return hashlib.sha256(json.dumps({"seed": SEED_VERSION, "attempts": size, "resources": resources}, sort_keys=True, default=str).encode()).hexdigest()


def make_service(factory):
    resources = SQLResourceRepository(factory)
    mastery = MasteryService(SQLMasteryRepository(factory), KnowledgeService(catalog=KnowledgeCatalogRepository(factory)),
                            resources, SQLCurriculumRepository(factory), SQLTierProgressRepository(factory))
    kwargs = {}
    if "read_repo" in inspect.signature(ReportService).parameters:
        from app.db.reports.repository import SQLReportReadRepository
        kwargs["read_repo"] = SQLReportReadRepository(factory)
    return ReportService(resources, SQLFeedbackRepository(factory), SQLFeedbackLoopRepository(factory),
                         SQLGenerationJobRepository(factory), mastery, SQLClaimRepository(factory),
                         SQLAuditRepository(factory), SQLDiagnosisRepository(factory), **kwargs)


def measure(size, repeats, directory):
    with tempfile.TemporaryDirectory(prefix="xh-report-bench-") as temp, ExitStack() as cleanup:
        engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{Path(temp) / 'report.db'}", connect_args={"check_same_thread": False}))
        cleanup.callback(engine.dispose)
        input_hash = seed_database(engine, size)
        factory = sessionmaker(bind=engine, expire_on_commit=False)
        profiles = ProfileService(SQLLearnerRepository(factory))
        service = make_service(factory)
        app = FastAPI()
        app.container = SimpleNamespace(profile_service=lambda: profiles, report_service=lambda: service)
        app.include_router(routes.router, prefix="/api/report")
        request = SimpleNamespace(app=app, state=SimpleNamespace())
        counts = {"sql": 0, "orm_objects": 0, "builds": 0}
        lock = Lock()

        def sql(*_args):
            with lock:
                counts["sql"] += 1

        def loaded(*_args):
            with lock:
                counts["orm_objects"] += 1

        original = service._build_report_once

        def build(*args, **kwargs):
            with lock:
                counts["builds"] += 1
            kwargs["now"] = NOW
            return original(*args, **kwargs)

        service._build_report_once = build
        # Freeze service/API clock input without replacing datetime in models.
        if hasattr(service, "_clock"):
            service._clock = lambda: NOW
        event.listen(engine, "before_cursor_execute", sql)
        event.listen(factory, "loaded_as_persistent", loaded)
        samples = {}
        with TestClient(app) as client:
            # Initial Mastery initialization is excluded from warm measurements.
            first = client.get(f"/api/report/{LEARNER}")
            assert first.status_code == 200, first.text
            etag = first.headers["etag"]

            def get():
                response = client.get(f"/api/report/{LEARNER}")
                assert response.status_code == 200, response.text
                return {"status": response.status_code}

            def conditional():
                response = client.get(f"/api/report/{LEARNER}", headers={"If-None-Match": etag})
                assert response.status_code == 304, response.text
                return {"status": 304}

            def page():
                response = client.get(f"/api/report/{LEARNER}/resource-credibility?limit=5")
                assert response.status_code == 200, response.text
                assert len(response.json()["items"]) == 5
                return {"returned_resources": len(response.json()["items"])}

            def poll():
                value = routes._stream_snapshot(request, service, LEARNER, 30)
                assert value is not None
                return {"subscribers": 1}

            def multi():
                with ThreadPoolExecutor(max_workers=3) as pool:
                    list(pool.map(lambda _i: poll(), range(3)))
                return {"subscribers": 3}

            for name, action in [("get", get), ("conditional_get", conditional), ("resource_page", page), ("sse_poll", poll), ("sse_multi_poll", multi)]:
                rows = []
                for _ in range(repeats):
                    with lock:
                        for key in counts:
                            counts[key] = 0
                    tracemalloc.start()
                    started = time.perf_counter()
                    details = action()
                    elapsed = time.perf_counter() - started
                    _, peak = tracemalloc.get_traced_memory()
                    tracemalloc.stop()
                    rows.append({**counts, "seconds": elapsed, "peak_bytes": peak, **details})
                samples[name] = {"samples": rows, "p95_seconds": sorted(row["seconds"] for row in rows)[max(0, (95 * len(rows) + 99) // 100 - 1)]}
                print(json.dumps({"size": size, "case": name, **samples[name]}, ensure_ascii=False), flush=True)
        engine.dispose()
    result = {"attempts": size, "resources": 30, "input_hash": input_hash, "cases": samples}
    (directory / f"size-{size}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", nargs="+", type=int, default=[100, 1000, 10000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.repeats < 3 or any(size < 10 for size in args.sizes):
        parser.error("at least 3 repeats and 10 attempts required")
    args.output.mkdir(parents=True, exist_ok=True)
    source_files = [Path(inspect.getsourcefile(ReportService)), Path(__file__).resolve()]
    metadata = {"python": platform.python_version(), "executable": sys.executable, "clock": NOW.isoformat(), "seed_version": SEED_VERSION,
                "source_hashes": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
                "measurement": "executed SQL statements / ORM loaded objects; P95 of small synthetic samples; not physical scans or production capacity"}
    results = [measure(size, args.repeats, args.output) for size in args.sizes]
    (args.output / "report.json").write_text(json.dumps({**metadata, "datasets": results}, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
