"""Live single-resource lecture generation + V2 review through the real chain.

Drives the *production* path only: ``generation_job_service.create_job`` freezes
the lecture policy at submission, ``generation_worker.py --once`` consumes the
job as the real SQLite worker, and the durable workflow runner executes the real
generation -> V2 review nodes against the live provider.  No scripted gateway,
no hand-built audit.

Requires ``RUN_LIVE_LLM=1`` and a real provider key.  The report contains statuses,
the review decision, the V3 audit/ledger/repair summary, and token totals -- never
prompts or generated bodies.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy import text

from app.containers import init_container
from app.db.shared.database import get_engine
from app.models.learning_documents.schemas import GenerateRequest

TERMINAL = {"completed", "failed", "cancelled"}


def _job_status(run_id: str) -> str:
    with get_engine().connect() as connection:
        row = connection.execute(
            text("select status from generation_jobs where run_id = :run_id"),
            {"run_id": run_id},
        ).first()
    return str(row[0]) if row else "missing"


def _summary(container, run_id: str) -> dict:
    engine = get_engine()
    with engine.connect() as connection:
        job = connection.execute(
            text("select status, created_at, started_at, finished_at, error_message "
                 "from generation_jobs where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().first()
        run = connection.execute(
            text("select status, workflow_status, final_decision, last_error_code, retrieval_status, "
                 "generation_attempt, revision_count, started_at, ended_at "
                 "from agent_runs where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().first()
        steps = connection.execute(
            text("select node_name, status, duration_ms, llm_attempts from agent_steps "
                 "where run_id = :run_id order by step_no"),
            {"run_id": run_id},
        ).mappings().all()
        resources = connection.execute(
            text("select resource_id, parent_resource_id, version, resource_type, review_status, "
                 "publication_status, length(content_text) as chars from generated_resources "
                 "where run_id = :run_id"),
            {"run_id": run_id},
        ).mappings().all()

    nodes: dict[str, dict] = {}
    totals = {"llm_calls": 0, "input_tokens": 0, "output_tokens": 0}
    for step in steps:
        attempts = json.loads(step["llm_attempts"]) if step["llm_attempts"] else []
        attempts = attempts if isinstance(attempts, list) else []
        tokens_in = sum(int(a.get("input_tokens") or 0) for a in attempts)
        tokens_out = sum(int(a.get("output_tokens") or 0) for a in attempts)
        totals["llm_calls"] += len(attempts)
        totals["input_tokens"] += tokens_in
        totals["output_tokens"] += tokens_out
        node = nodes.setdefault(step["node_name"], {
            "steps": 0, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0, "statuses": [],
        })
        node["steps"] += 1
        node["llm_calls"] += len(attempts)
        node["input_tokens"] += tokens_in
        node["output_tokens"] += tokens_out
        node["statuses"].append(step["status"])

    # Read the durable review audit (V3 for contract 2.0) from the audit repo.
    review_evidence = None
    try:
        repo = container.audit_repository()
        for step in repo.list_steps(run_id):
            if step.node_name in {"review", "reviewer"}:
                audit = repo.get_step_review_audit(run_id, step.step_id)
                if audit is None:
                    continue
                review_evidence = {
                    "schema_version": audit.schema_version,
                    "decision": audit.decision,
                    "resources": [
                        {"resource_id": r.resource_id, "resource_type": r.resource_type,
                         "decision": r.decision, "structure_status": r.structure_status,
                         "semantic_status": r.semantic_status}
                        for r in audit.resources
                    ],
                    "ledgers": [
                        {
                            "resource_id": ledger.binding.resource_id,
                            "observations": len(ledger.observations),
                            "last_decision": ledger.observations[-1].decision,
                            "coverage_rate": ledger.observations[-1].coverage_rate,
                            "open_issues": sum(1 for i in ledger.issues if i.status == "open"),
                            "targets": [t.model_dump(mode="json") for t in ledger.observations[-1].output.targets],
                        }
                        for ledger in audit.lecture_ledgers
                    ],
                    "repairs": [
                        {
                            "review_id": r.review_id, "resource_id": r.resource_id,
                            "error_codes": r.error_codes, "corrected": r.corrected,
                            "first_call_id": r.first_call_id, "correction_call_id": r.correction_call_id,
                            "final_call_id": r.final_call_id, "stop_reason": r.stop_reason,
                            "first_attempts": r.first_attempts, "correction_attempts": r.correction_attempts,
                        }
                        for r in audit.repairs
                    ],
                }
    except Exception as exc:  # pragma: no cover - report the read failure, keep the raw rows
        review_evidence = {"error": type(exc).__name__, "detail": str(exc)[:400]}

    return {
        "run_id": run_id,
        "job": dict(job) if job else None,
        "run": dict(run) if run else None,
        "llm_usage": {**totals, "total_tokens": totals["input_tokens"] + totals["output_tokens"]},
        "nodes": nodes,
        "resources": [dict(item) for item in resources],
        "review_audit": review_evidence,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--learner-id", default=os.getenv("LIVE_LEARNER_ID", "").strip())
    parser.add_argument("--resource-types", nargs="+", default=["讲义"],
                        help="one or more resource types (claim check needs exactly one)")
    parser.add_argument("--target-node", default="", help="empty keeps production auto recommendation")
    parser.add_argument("--max-iterations", type=int, default=2)
    parser.add_argument("--include-claim-check", action="store_true", default=False)
    parser.add_argument("--timeout-seconds", type=int, default=1800)
    parser.add_argument("--report-path", default=".live-lecture-v2-runs/latest.json")
    args = parser.parse_args(argv)

    if os.getenv("RUN_LIVE_LLM") != "1":
        raise SystemExit("set RUN_LIVE_LLM=1")

    container = init_container()
    learners = container.profile_service().repo.list_all()
    if not learners:
        raise SystemExit("no learner profile found")
    learner = learners.get(args.learner_id) if args.learner_id else next(iter(learners.values()))
    if learner is None:
        raise SystemExit(f"learner profile not found: {args.learner_id}")

    with get_engine().connect() as connection:
        queued = int(connection.execute(
            text("select count(*) from generation_jobs where status = 'queued'")
        ).scalar() or 0)
    if queued:
        raise SystemExit(f"{queued} queued generation job(s) present; drain them before this run")

    request = GenerateRequest(
        learner_id=learner.learner_id,
        topic=learner.learning_goal or "当前学习主题",
        knowledge_base_id=learner.knowledge_base_id,
        resource_types=list(args.resource_types),
        include_review=True,
        include_claim_check=args.include_claim_check,
        max_iterations=args.max_iterations,
        claim_max_iterations=0,
        profile_focus_mode="auto",
        target_skill_nodes=[args.target_node] if args.target_node else [],
    )
    job = container.generation_job_service().create_job(learner, request)
    run_id = job.run_id
    print(json.dumps({"created": run_id, "learner_id": learner.learner_id}, ensure_ascii=False), flush=True)

    started = time.monotonic()
    timed_out = False
    try:
        subprocess.run(
            [sys.executable, str(BACKEND_ROOT / "scripts" / "generation_worker.py"), "--once"],
            cwd=BACKEND_ROOT,
            check=False,
            timeout=args.timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        timed_out = True
    while time.monotonic() - started < args.timeout_seconds:
        if _job_status(run_id) in TERMINAL:
            break
        time.sleep(2)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "learner_id": learner.learner_id,
        "configuration": {
            "resource_types": list(args.resource_types),
            "target_node": args.target_node or "auto",
            "include_review": True,
            "include_claim_check": args.include_claim_check,
            "max_iterations": args.max_iterations,
        },
        "timed_out": timed_out,
        "elapsed_seconds": round(time.monotonic() - started, 2),
        **_summary(container, run_id),
    }

    path = Path(args.report_path)
    if not path.is_absolute():
        path = (REPO_ROOT / path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n")

    print(json.dumps({
        "report_path": str(path),
        "job_status": (report["job"] or {}).get("status"),
        "run_status": (report["run"] or {}).get("status"),
        "final_decision": (report["run"] or {}).get("final_decision"),
        "review_audit_schema": (report["review_audit"] or {}).get("schema_version"),
        "llm_usage": report["llm_usage"],
    }, ensure_ascii=False), flush=True)
    if timed_out:
        return 5
    return 0 if (report["job"] or {}).get("status") == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
