"""Run six real generation jobs through the production GenerationJobService."""
from __future__ import annotations
import json, os, sys, uuid
from typing import Any
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
from app.config import get_settings, is_placeholder_api_key
from app.containers import init_container
from app.core.learning_tiers import difficulty_for_tier
from app.models.learning_documents.schemas import GenerateRequest

RESOURCE_TYPES = ("讲义", "实操指南", "分阶测试题", "复习清单", "案例分析", "个性化纠错训练包")

def _correction_focus(container, learner):
    mastery = container.mastery_service()
    snapshot = mastery.focus_snapshot(learner, mode="auto", explicit_node_ids=[])
    data = snapshot.model_dump(mode="json")
    # CorrectionTrainingPackageAgent consumes this service-owned snapshot.
    data.setdefault("schema_version", "CorrectionFocusSnapshotV1")
    # The correction-package admission gate requires targets to match the
    # service-owned snapshot exactly; initialize only from adopted nodes.
    data["ordered_target_nodes"] = [
        {"skill_node_id": node_id} for node_id in snapshot.adopted_node_ids
    ]
    nodes = {node.node_id: node for node in container.knowledge_service().list_skill_nodes(learner.knowledge_base_id)}
    tiers = {int(nodes[node_id].tier) for node_id in snapshot.adopted_node_ids if node_id in nodes}
    data["difficulty"] = difficulty_for_tier(next(iter(tiers))) if len(tiers) == 1 else (learner.skill_level or "中级")
    data.setdefault("scaffolding_level", "medium")
    data.setdefault("focus_snapshot_hash", str(uuid.uuid4()))
    return data

def run_one(container, learner, resource_type):
    job_service = container.generation_job_service()
    constraints = {}
    target_skill_nodes = []
    if resource_type == "个性化纠错训练包":
        constraints["correction_focus_snapshot"] = _correction_focus(container, learner)
        constraints["selection_type"] = "correction_package"
        target_skill_nodes = list(snapshot_node["skill_node_id"] for snapshot_node in constraints["correction_focus_snapshot"]["ordered_target_nodes"])
    req = GenerateRequest(
        learner_id=learner.learner_id, topic=learner.learning_goal or "当前学习主题",
        knowledge_base_id=learner.knowledge_base_id, resource_types=[resource_type],
        target_skill_nodes=target_skill_nodes,
        include_review=True, include_claim_check=True, max_iterations=1,
        claim_max_iterations=1, profile_focus_mode="auto", constraints=constraints,
    )
    job = job_service.create_job(learner, req)
    job_service.run_job(learner, req, job.run_id, job.batch_id)
    final = job_service.get_job(job.run_id)
    audit = container.audit_repository().get_run(job.run_id)
    def _value(value):
        return getattr(value, "value", value)

    result = {
        "resource_type": resource_type,
        "run_id": job.run_id,
        "job_status": _value(getattr(final, "job_status", None)),
        "run_status": _value(getattr(audit, "status", None)),
        "workflow_status": getattr(audit, "workflow_status", None),
        "execution_status": getattr(audit, "execution_status", None),
        "current_node": getattr(audit, "current_node", None),
        "final_decision": getattr(audit, "final_decision", None),
        "error": getattr(final, "error_message", None),
        "last_error_code": getattr(audit, "last_error_code", None),
        "revision_count": getattr(audit, "revision_count", None),
        "claim_revision_count": getattr(audit, "claim_revision_count", None),
        "retrieval_status": getattr(audit, "retrieval_status", None),
        "claim_check_status": getattr(audit, "claim_check_status", None),
    }
    # Read the same durable projections used by the run-query API.  This is
    # intentionally collected after run_job returns so the report includes
    # the complete ordinary-review and Claim-review rounds, including their
    # revision instructions and concrete step/retrieval errors.
    try:
        timeline = container.run_query_service().get_timeline(job.run_id, limit=500)
        steps = [item.model_dump(mode="json") for item in timeline.steps]
        result["failure_details"] = {
            "run": timeline.run.model_dump(mode="json"),
            "failed_steps": [
                {
                    "step_id": item.get("step_id"),
                    "node_name": item.get("node_name"),
                    "agent_name": item.get("agent_name"),
                    "status": item.get("status"),
                    "error_code": item.get("error_code"),
                    "error_message": item.get("error_message"),
                    "retrieval_status": item.get("retrieval_status"),
                    "retrieval_profile": item.get("retrieval_profile"),
                    "generation_attempt": item.get("generation_attempt"),
                }
                for item in steps
                if item.get("status") not in {"success", "succeeded", "completed"}
                or item.get("error_code")
                or item.get("retrieval_status") not in {None, "success", "succeeded", "available"}
            ],
            "reviews": timeline.reviews,
            "events": [
                item.model_dump(mode="json") for item in timeline.events
                if str(getattr(item, "event_type", "")).lower().find("fail") >= 0
                or str(getattr(item, "event_type", "")).lower().find("revision") >= 0
            ],
        }
        claims = container.run_query_service().get_claims(job.run_id)
        result["claim_audit"] = claims.model_dump(mode="json")
    except Exception as exc:
        result["failure_details_error"] = {
            "type": type(exc).__name__, "detail": str(exc)[:1000]
        }
    return result

def run_process(resource_type: str, learner_id: str) -> dict[str, Any]:
    """Process entrypoint: no DB session, Chroma client, or model is shared."""
    container = init_container()
    learner = container.profile_service().get(learner_id)
    if learner is None:
        raise RuntimeError(f"learner profile not found: {learner_id}")
    return run_one(container, learner, resource_type)

def main():
    if os.getenv("RUN_LIVE_LLM") != "1": raise SystemExit("set RUN_LIVE_LLM=1")
    settings = get_settings()
    if is_placeholder_api_key(settings.llm_api_key.get_secret_value().strip()): raise SystemExit("real LLM_API_KEY required")
    container = init_container()
    learners = container.profile_service().repo.list_all()
    if not learners: raise SystemExit("no learner profile found in configured database")
    learner = next(iter(learners.values()))
    out=[]
    selected_types = tuple(item.strip() for item in os.getenv("LIVE_RESOURCE_TYPES", "").split(",") if item.strip()) or RESOURCE_TYPES
    unknown = [item for item in selected_types if item not in RESOURCE_TYPES]
    if unknown:
        raise SystemExit(f"unknown resource type(s): {unknown}")
    workers = max(1, min(3, int(os.getenv("LIVE_BATCH_WORKERS", "3")), len(selected_types)))
    with ProcessPoolExecutor(max_workers=workers) as pool:
        # Each child process owns its container, SQLite session factory,
        # Chroma client, embedding model, and LLM gateway. Six jobs are queued
        # while only a bounded number of Durable-style workers execute.
        fs={pool.submit(run_process, t, learner.learner_id): t for t in selected_types}
        for f in as_completed(fs):
            try: out.append(f.result())
            except Exception as e: out.append({"resource_type":fs[f],"error_type":type(e).__name__,"error":str(e)[:1000]})
    out.sort(key=lambda x: RESOURCE_TYPES.index(x["resource_type"]))
    passed=sum(x.get("run_status") in {"completed","success"} for x in out)
    report = {"created_at":datetime.now(timezone.utc).isoformat(),"learner_id":learner.learner_id,
      "configuration":{"batches":len(selected_types),"include_claim_check":True,"max_iterations":1,"claim_max_iterations":1,"worker_concurrency":workers,"one_resource_per_batch":True},
      "summary":{"total":len(out),"passed":passed,"pass_rate":passed/len(out) if out else 0},"batches":out}
    report_path = Path(os.getenv(
        "LIVE_REPORT_PATH",
        str(BACKEND_ROOT.parent / ".live-claim-runs" / "live-real-generation-report.json"),
    ))
    if not report_path.is_absolute():
        report_path = (Path.cwd() / report_path).resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    # Timeline projections may still contain datetime values in nested review
    # payloads; stringify those values so a completed run can always be
    # persisted even when a provider returns non-JSON-native metadata.
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"report_path": str(report_path), **report}, ensure_ascii=False, indent=2, default=str))
if __name__ == "__main__": main()
