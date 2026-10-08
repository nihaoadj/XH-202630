"""Resume interrupted real GenerationJobService runs from durable checkpoints."""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed

# Ensure the repository package wins over any unrelated installed ``app``
# package when this file is launched as ``python scripts/...``.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.containers import init_container
from app.models.learning_documents.schemas import GenerateRequest


def resume_one(run_id: str) -> dict:
    container = init_container()
    row = sqlite3.connect("data/domain_knowledge_writable_probe.db").execute(
        "select input_payload, learner_id from agent_runs where run_id = ?", (run_id,)
    ).fetchone()
    if row is None:
        raise RuntimeError(f"run not found: {run_id}")
    request = GenerateRequest.model_validate(json.loads(row[0]))
    learner = container.profile_service().get(row[1])
    if learner is None:
        raise RuntimeError(f"learner not found: {row[1]}")
    container.generation_job_service().run_job(learner, request, run_id)
    audit = container.audit_repository().get_run(run_id)
    value = lambda x: getattr(x, "value", x)
    return {
        "run_id": run_id,
        "resource_type": request.resource_types[0],
        "status": value(audit.status),
        "current_node": audit.current_node,
        "revision_count": audit.revision_count,
        "final_decision": value(audit.final_decision),
        "last_error_code": audit.last_error_code,
    }


def main() -> None:
    run_ids = sys.argv[1:]
    if not run_ids:
        raise SystemExit("usage: resume_live_runs.py RUN_ID [...]")
    with ProcessPoolExecutor(max_workers=min(3, len(run_ids))) as pool:
        futures = [pool.submit(resume_one, run_id) for run_id in run_ids]
        for future in as_completed(futures):
            print(json.dumps(future.result(), ensure_ascii=False))


if __name__ == "__main__":
    main()
