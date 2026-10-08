"""Compile a JSON report from already executed durable run IDs (no LLM calls)."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.containers import init_container


def main() -> None:
    run_ids = sys.argv[1:]
    if len(run_ids) != 6:
        raise SystemExit("usage: compile_live_report.py RUN_ID ... (exactly six)")
    container = init_container()
    profile = next(iter(container.profile_service().repo.list_all().values()))
    query = container.run_query_service()
    db_rows = {
        row[0]: json.loads(row[1] or "{}")
        for row in sqlite3.connect("data/domain_knowledge_writable_probe.db").execute(
            "select run_id, input_payload from agent_runs where run_id in (%s)"
            % ",".join("?" * len(run_ids)), run_ids
        )
    }
    batches = []
    for run_id in run_ids:
        audit = container.audit_repository().get_run(run_id)
        if audit is None:
            batches.append({"run_id": run_id, "run_status": "missing"})
            continue
        job = container.generation_job_service().get_job(run_id)
        value = lambda x: getattr(x, "value", x)
        timeline = query.get_timeline(run_id, limit=500)
        steps = [item.model_dump(mode="json") for item in timeline.steps]
        claims = query.get_claims(run_id)
        batches.append({
            "resource_type": db_rows.get(run_id, {}).get("resource_types", [None])[0],
            "run_id": run_id,
            "job_status": value(getattr(job, "job_status", None)),
            "run_status": value(audit.status),
            "workflow_status": value(audit.workflow_status),
            "execution_status": value(audit.execution_status),
            "current_node": audit.current_node,
            "final_decision": value(audit.final_decision),
            "error": getattr(job, "error_message", None),
            "last_error_code": audit.last_error_code,
            "revision_count": audit.revision_count,
            "retrieval_status": value(audit.retrieval_status),
            "claim_check_status": value(getattr(audit, "claim_check_status", None)),
            "failure_details": {
                "run": timeline.run.model_dump(mode="json"),
                "failed_steps": [
                    {k: item.get(k) for k in (
                        "step_id", "node_name", "agent_name", "status", "error_code",
                        "error_message", "retrieval_status", "retrieval_profile", "generation_attempt"
                    )}
                    for item in steps
                    if item.get("status") not in {"success", "succeeded", "completed"}
                    or item.get("error_code")
                    or item.get("retrieval_status") not in {None, "success", "succeeded", "available"}
                ],
                "reviews": [getattr(item, "model_dump", lambda **_: item)(mode="json") for item in timeline.reviews],
                "events": [item.model_dump(mode="json") for item in timeline.events
                           if "fail" in str(getattr(item, "event_type", "")).lower()
                           or "revision" in str(getattr(item, "event_type", "")).lower()],
            },
            "claim_audit": claims.model_dump(mode="json"),
        })
    passed = sum(item.get("run_status") in {"completed", "success"} and item.get("final_decision") == "审核通过" for item in batches)
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "learner_id": profile.learner_id,
        "configuration": {"batches": 6, "include_claim_check": True, "max_iterations": 1,
                          "claim_max_iterations": 1, "worker_concurrency": 3},
        "summary": {"total": 6, "passed": passed, "pass_rate": passed / 6},
        "batches": batches,
    }
    path = Path(os.getenv("LIVE_REPORT_PATH", str(Path.cwd().parent / ".live-claim-runs" / "final-six-real-report.json")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(path)


if __name__ == "__main__":
    main()
