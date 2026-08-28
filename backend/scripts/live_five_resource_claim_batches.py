"""Explicit real-provider acceptance for five one-resource review batches.

Run only with RUN_LIVE_LLM=1.  The JSON report contains statuses and review
findings, never prompts, provider credentials, or generated resource bodies.
"""

from __future__ import annotations

import json
import os
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Executing a file under ``scripts/`` otherwise puts that directory before the
# backend package root, where an unrelated installed ``app`` package can win.
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.agents.resource_agents.registry import get_resource_agent
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_decide_node, claim_extract_node, claim_judge_node,
)
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.config import get_settings, is_placeholder_api_key
from app.core.llm.gateway import default_llm_gateway
from app.core.retrieval.evidence import source_refs_from_evidence
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import ResourceGenerationContext
from tests.fakes.evidence import make_evidence


RESOURCE_TYPES = ("讲义", "实操指南", "分阶测试题", "复习清单", "案例分析", "个性化纠错训练包")
EVIDENCE_TEXT = (
    "倒数排名融合（RRF）对每个候选文档在多个检索结果列表中的排名计算倒数得分并求和。"
    "常用形式为 score(d)=sum(1/(k+rank_i(d)))。参数 k 用于平滑排名靠前结果的影响，"
    "最终按融合得分从高到低排序；RRF 不要求不同检索器的原始分数可比较。"
)


def _resource(artifact: Any, spec: Any, run_id: str, evidence: list[Any]) -> LearningResource:
    data = artifact.artifact_data
    return LearningResource(
        resource_id=str(uuid.uuid4()), learner_id="live-acceptance-learner",
        run_id=run_id, batch_id=run_id, topic="RRF 排名融合", resource_type=spec.resource_type,
        resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
        representation=artifact.metadata.representation, difficulty=artifact.difficulty,
        content_text=artifact.content_text, storage_type=artifact.storage_type, mime_type=artifact.mime_type,
        knowledge_points=artifact.knowledge_points, source_refs=source_refs_from_evidence(evidence), version=1,
        assessment_payload=data.get("assessment_package"),
        review_practice_payload=data.get("review_practice_package"),
        practice_guide_payload=data.get("practice_guide_package"),
    )


def run_batch(resource_type: str) -> dict[str, Any]:
    run_id = f"live-five-batch-{resource_type}-{uuid.uuid4()}"
    evidence = [make_evidence(
        evidence_id=f"ev-{uuid.uuid4()}", knowledge_base_id="kb-live-acceptance",
        document_id="rrf", document_version="v1", chunk_id=f"chunk-{uuid.uuid4()}",
        excerpt=EVIDENCE_TEXT, query="RRF 排名融合",
    )]
    correction_focus = {
        "schema_version": "CorrectionFocusSnapshotV1",
        "focus_snapshot_hash": f"live-focus-{uuid.uuid4()}",
        "difficulty": "初级", "scaffolding_level": "high",
        "ordered_target_nodes": [{
            "skill_node_id": "kp-rrf", "name": "RRF 排名融合", "status": "weak",
            "score_band": "low", "reason_codes": ["LIVE_ACCEPTANCE"],
            "failed_dimensions": ["concept_application"],
            "teaching_strategies": ["先辨析排名与原始分数"],
            "success_criteria": ["能说明 RRF 的排名倒数求和规则"],
        }],
    }
    learning_plan = {"learning_path": [{"order": 1, "topic": "RRF 排名融合", "reason": "掌握多路检索融合"}]}
    if resource_type == "个性化纠错训练包":
        learning_plan["correction_focus_snapshot"] = correction_focus
    spec = build_resource_specs(
        run_id=run_id, resource_types=[resource_type], topic="RRF 排名融合", difficulty="初级",
        learning_plan=learning_plan,
        evidence=evidence,
    )[0]
    gateway = default_llm_gateway()
    context = ResourceGenerationContext(
        run_id=run_id, batch_id=run_id, topic="RRF 排名融合", evidence=evidence,
        learner_profile_summary={"skill_level": "初级", "weak_points": ["检索融合"], "strong_points": [], "learning_goal": "理解 RRF"},
        learning_path=[{"order": 1, "topic": "RRF 排名融合", "reason": "掌握多路检索融合"}],
        constraints=({"correction_focus_snapshot": correction_focus}
                     if resource_type == "个性化纠错训练包" else {}), generation_attempt=1,
    )
    artifact = get_resource_agent(resource_type).generate(spec, context, llm_gateway=gateway)
    resource = _resource(artifact, spec, run_id, evidence)
    state: dict[str, Any] = {
        "run_id": run_id, "generation_attempt": 1, "revision_count": 0, "claim_revision_count": 0,
        "max_iterations": 1, "claim_max_iterations": 1, "workflow_deadline_at": None,
        "target_skill_nodes": [], "retrieved_evidence": evidence, "generated_resources": [resource],
        "resource_executions": [], "resource_review_results": {}, "review_result": {},
        "include_review": True, "include_claim_check": True, "claim_check_status": "pending",
        "claim_metrics": {}, "claim_failed_resource_ids": [], "claim_eligible_resource_ids": [],
        "trace": [], "errors": [], "difficulty_preference": "初级",
        "constraints": ({"correction_focus_snapshot": correction_focus}
                        if resource_type == "个性化纠错训练包" else {}), "generation_mode": "standard",
    }
    state.update(review_node(state, llm_gateway=gateway))
    state.update(claim_extract_node(state, llm_gateway=gateway))
    state.update(claim_judge_node(state, llm_gateway=gateway))
    state.update(claim_decide_node(state))
    review = state["review_result"]
    issues = review.get("issues", [])
    return {
        "resource_type": resource_type, "run_id": run_id,
        "ordinary_review_decision": state.get("resource_review_results", {}).get(resource.resource_id, {}).get("decision"),
        "claim_review_decision": review.get("decision"),
        "final_decision": review.get("decision"),
        "revision_count": state.get("revision_count"), "claim_revision_count": state.get("claim_revision_count"),
        "issue_codes": sorted({str(item.get("code")) for item in issues if isinstance(item, dict)}),
        "issue_count": len(issues), "claim_metrics": state.get("claim_metrics", {}).get(resource.resource_id, {}),
        "errors": [{"code": item.get("code"), "source": item.get("source")}
                   for item in state.get("errors", []) if isinstance(item, dict)],
    }


def main() -> int:
    if os.getenv("RUN_LIVE_LLM") != "1":
        raise SystemExit("set RUN_LIVE_LLM=1 to authorize real-provider calls")
    if is_placeholder_api_key(get_settings().llm_api_key.get_secret_value().strip()):
        raise SystemExit("a real LLM_API_KEY is required")
    results: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(run_batch, resource_type): resource_type for resource_type in RESOURCE_TYPES}
        for future in as_completed(futures):
            resource_type = futures[future]
            try:
                results.append(future.result())
            except Exception as exc:
                results.append({"resource_type": resource_type, "error_type": type(exc).__name__, "error": str(exc)[:400]})
    results.sort(key=lambda item: RESOURCE_TYPES.index(item["resource_type"]))
    passed = sum(item.get("final_decision") == "approve" for item in results)
    report = {"schema_version": "1.0", "created_at": datetime.now(timezone.utc).isoformat(),
              "configuration": {"include_claim_check": True, "max_iterations": 1, "claim_max_iterations": 1, "parallel_batches": 6},
              "summary": {"total": len(results), "passed": passed, "pass_rate": passed / len(results), "failed": len(results) - passed},
              "batches": results}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if len(results) == len(RESOURCE_TYPES) else 1


if __name__ == "__main__":
    sys.exit(main())
