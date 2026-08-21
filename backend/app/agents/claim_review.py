"""P0-06 independent Claim extraction, judgement and deterministic routing."""

from __future__ import annotations

import json
import uuid
from collections import defaultdict
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ErrorCode
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.models.agent_contracts import build_trace_item, make_error_info, start_step
from app.models.claims import (
    ClaimExtractionLLMOutput,
    ClaimJudgementLLMOutput,
    ClaimMetricStatus,
    ClaimRecord,
    ClaimVerdict,
    compute_claim_metric,
    materialize_claims,
    materialize_judgements,
)
from app.models.llm import LLMCallContext
from app.models.workflow import ClaimCheckStatus, ReviewDecision, StepStatus


EXTRACTOR_PROMPT_VERSION = "p0-06-extract-v1"
JUDGE_PROMPT_VERSION = "p0-06-judge-v1"

EXTRACTOR_PROMPT = """你是独立 Claim 抽取器。仅从给定资源原文抽取可单独判断的陈述。
resource_id 必须从输入中原样选择；source_text 必须是资源原文的连续精确子串，
source_start/source_end 使用 Python 字符下标且 end 为开区间。事实陈述标 factual，
教学动作标 instructional，主观/过渡表达标 non_factual。evidence_id 和 knowledge_point_id
只能从输入白名单选择，不能创造 ID。每个非空资源至少输出一个 Claim，不要输出解释。"""

JUDGE_PROMPT = """你是独立 Claim 证据判定器。逐条且仅依据本次冻结 Evidence 判定。
每个 claim_id 必须恰好出现一次。事实 Claim 只能判 supported、contradicted、not_in_evidence；
instructional/non_factual Claim 必须判 non_factual。supported/contradicted 必须引用白名单
evidence_ids，not_in_evidence/non_factual 禁止引用证据。不能使用常识补全，不能创造 ID。"""


def _failure(
    state: AgentState,
    *,
    node_name: str,
    code: ErrorCode,
    detail: str,
    llm_error: LLMGatewayError | None = None,
) -> dict[str, Any]:
    error = llm_error.error if llm_error else make_error_info(
        code,
        source=node_name,
        attempt=state.get("generation_attempt", 1),
        category="claim_audit",
        safe_detail=detail[:256],
    )
    review = dict(state.get("review_result", {}))
    review.update({
        "decision": ReviewDecision.HUMAN_REVIEW.value,
        "status": ReviewDecision.HUMAN_REVIEW.value,
        "passed": False,
        "claim_check_status": ClaimCheckStatus.FAILED.value,
        "claim_metric_status": ClaimMetricStatus.INCOMPLETE.value,
        "claim_hallucination_rate": None,
    })
    step_context = start_step(state)
    trace = build_trace_item(
        state,
        agent_name=node_name,
        action="Claim 级审核",
        status=StepStatus.HUMAN_REVIEW,
        input_summary=f"资源数：{len(state.get('generated_resources', []))}",
        output_summary="Claim 审核失败，转人工复核",
        decision_reason="Claim 或 Evidence 的机器判定结果未通过确定性校验。",
        resource_ids=[item.resource_id for item in state.get("generated_resources", [])],
        review_ids=list(review.get("review_ids", {}).values()),
        error=error,
        step_context=step_context,
        llm_metadata=llm_error.trace_metadata() if llm_error else None,
    )
    return {
        "review_result": review,
        "claim_check_status": ClaimCheckStatus.FAILED.value,
        "current_node": node_name,
        "trace": [trace],
        "errors": [error.model_dump(mode="json")],
    }


def claim_extract_node(state: AgentState, *, llm_gateway: LLMGateway) -> dict[str, Any]:
    # HTML is a presentation derived from the canonical practice-guide text;
    # claim review, like normal review, assesses only canonical text.
    resources = [
        item for item in state.get("generated_resources", [])
        if item.representation.value == "text"
    ]
    evidence = state.get("retrieved_evidence", [])
    review_ids = state.get("review_result", {}).get("review_ids", {})
    step_context = start_step(state)
    if not resources or any(not item.content_text for item in resources):
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="resource content unavailable",
        )
    if set(review_ids) != {item.resource_id for item in resources}:
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="review/resource boundary mismatch",
        )
    claims: list[ClaimRecord] = []
    allowed_evidence = {item.evidence_id for item in evidence}
    allowed_nodes = set(state.get("target_skill_nodes", []))
    failed_resource_ids: list[str] = []
    errors: list[dict[str, Any]] = []
    last_result = None
    for resource in resources:
        try:
            payload = {
                "allowed_evidence": [
                    {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
                    for item in evidence
                ],
                "allowed_knowledge_point_ids": state.get("target_skill_nodes", []),
                "resources": [{
                    "resource_id": resource.resource_id,
                    "resource_version": resource.version,
                    "content_text": resource.content_text,
                }],
            }
            result = llm_gateway.invoke_structured(
                messages=[SystemMessage(content=EXTRACTOR_PROMPT), HumanMessage(content=json.dumps(payload, ensure_ascii=False))],
                output_schema=ClaimExtractionLLMOutput,
                context=LLMCallContext(
                    run_id=state.get("run_id", "direct-node-call"),
                    step_id=step_context["step_id"],
                    node_name="claim_extractor",
                    schema_name=ClaimExtractionLLMOutput.__name__,
                    generation_attempt=state.get("generation_attempt", 1),
                    workflow_deadline_at=state.get("workflow_deadline_at"),
                ),
                options=llm_gateway.options_for("claim_extractor", temperature=0.0),
            )
            batches = result.output.resources
            if len(batches) != 1 or batches[0].resource_id != resource.resource_id:
                raise ValueError("extractor resource boundary mismatch")
            if not batches[0].claims:
                raise ValueError("each non-empty resource requires at least one claim")
            claims.extend(materialize_claims(
                candidates=batches[0].claims,
                resource_content=resource.content_text or "",
                resource_id=resource.resource_id,
                resource_version=resource.version,
                review_id=review_ids[resource.resource_id],
                run_id=state.get("run_id", "direct-node-call"),
                allowed_evidence_ids=allowed_evidence,
                allowed_knowledge_point_ids=allowed_nodes,
                extractor_prompt_version=EXTRACTOR_PROMPT_VERSION,
                extractor_model=result.model_name,
            ))
            last_result = result
        except LLMGatewayError as exc:
            failed_resource_ids.append(resource.resource_id)
            errors.append(exc.error.model_dump(mode="json"))
        except (ValueError, KeyError) as exc:
            failed_resource_ids.append(resource.resource_id)
            errors.append(make_error_info(
                ErrorCode.CLAIM_EXTRACTION_INVALID,
                source="claim_extractor",
                attempt=state.get("generation_attempt", 1),
                category="claim_audit",
                safe_detail=str(exc)[:256],
            ).model_dump(mode="json"))
    if not claims:
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="all resource claim extractions failed",
        )
    trace = build_trace_item(
        state,
        agent_name="claim_extractor",
        action="独立 Claim 抽取",
        status=StepStatus.DEGRADED if failed_resource_ids else StepStatus.SUCCESS,
        input_summary=f"资源数：{len(resources)}；冻结证据数：{len(evidence)}",
        output_summary=(f"已抽取 {len(claims)} 条 Claim；"
                        f"失败资源 {len(failed_resource_ids)} 个"),
        decision_reason="成功资源通过白名单校验；失败资源被隔离并转人工复核。",
        evidence_refs=[item.evidence_id for item in evidence],
        resource_ids=[item.resource_id for item in resources],
        review_ids=list(review_ids.values()),
        step_context=step_context,
        llm_metadata=last_result.trace_metadata() if last_result else None,
    )
    return {
        "extracted_claims": [item.model_dump(mode="json") for item in claims],
        "claim_failed_resource_ids": failed_resource_ids,
        "claim_check_status": ClaimCheckStatus.PENDING.value,
        "current_node": "claim_extractor",
        "trace": [trace],
        "errors": errors,
    }


def claim_judge_node(state: AgentState, *, llm_gateway: LLMGateway) -> dict[str, Any]:
    step_context = start_step(state)
    try:
        claims = [ClaimRecord.model_validate(item) for item in state.get("extracted_claims", [])]
    except ValueError as exc:
        return _failure(state, node_name="claim_judge",
                        code=ErrorCode.CLAIM_JUDGEMENT_INVALID, detail=str(exc))
    if not claims:
        return _failure(state, node_name="claim_judge",
                        code=ErrorCode.CLAIM_JUDGEMENT_INVALID, detail="no validated claims")
    evidence = state.get("retrieved_evidence", [])
    claims_by_resource: dict[str, list[ClaimRecord]] = defaultdict(list)
    for item in claims:
        claims_by_resource[item.resource_id].append(item)
    judgements = []
    failed_resource_ids = set(state.get("claim_failed_resource_ids", []))
    errors: list[dict[str, Any]] = []
    last_result = None
    for resource_id, resource_claims in claims_by_resource.items():
        try:
            payload = {
                "allowed_evidence": [
                    {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
                    for item in evidence
                ],
                "claims": [
                    {
                        "claim_id": item.claim_id,
                        "claim_type": item.claim_type.value,
                        "claim_text": item.claim_text,
                        "resource_id": item.resource_id,
                        "resource_version": item.resource_version,
                    }
                    for item in resource_claims
                ],
            }
            result = llm_gateway.invoke_structured(
                messages=[SystemMessage(content=JUDGE_PROMPT), HumanMessage(content=json.dumps(payload, ensure_ascii=False))],
                output_schema=ClaimJudgementLLMOutput,
                context=LLMCallContext(
                    run_id=state.get("run_id", "direct-node-call"),
                    step_id=step_context["step_id"],
                    node_name="claim_judge",
                    schema_name=ClaimJudgementLLMOutput.__name__,
                    generation_attempt=state.get("generation_attempt", 1),
                    workflow_deadline_at=state.get("workflow_deadline_at"),
                ),
                options=llm_gateway.options_for("claim_judge", temperature=0.0),
            )
            judgements.extend(materialize_judgements(
                claims=resource_claims,
                candidates=result.output.judgements,
                allowed_evidence_ids={item.evidence_id for item in evidence},
                judge_prompt_version=JUDGE_PROMPT_VERSION,
                judge_model=result.model_name,
            ))
            last_result = result
        except LLMGatewayError as exc:
            failed_resource_ids.add(resource_id)
            errors.append(exc.error.model_dump(mode="json"))
        except (ValueError, KeyError) as exc:
            failed_resource_ids.add(resource_id)
            errors.append(make_error_info(
                ErrorCode.CLAIM_JUDGEMENT_INVALID,
                source="claim_judge",
                attempt=state.get("generation_attempt", 1),
                category="claim_audit",
                safe_detail=str(exc)[:256],
            ).model_dump(mode="json"))
    judgements_by_resource: dict[str, list] = defaultdict(list)
    for item in judgements:
        judgements_by_resource[item.resource_id].append(item)
    metrics = {
        resource_id: compute_claim_metric(items, judgements_by_resource[resource_id])
        for resource_id, items in claims_by_resource.items()
    }
    for resource_id in failed_resource_ids:
        if resource_id not in metrics:
            metrics[resource_id] = {
                "metric_status": ClaimMetricStatus.INCOMPLETE.value,
                "claim_hallucination_rate": None,
                "claim_total": 0,
                "factual_claim_total": 0,
                "supported_claim_total": 0,
                "contradicted_claim_total": 0,
                "not_in_evidence_claim_total": 0,
                "non_factual_claim_total": 0,
                "incomplete_claim_total": 1,
            }
    trace = build_trace_item(
        state,
        agent_name="claim_judge",
        action="冻结证据 Claim 判定",
        status=StepStatus.DEGRADED if failed_resource_ids else StepStatus.SUCCESS,
        input_summary=f"Claim 数：{len(claims)}；冻结证据数：{len(evidence)}",
        output_summary=(f"完成 {len(judgements)} 条独立判定；"
                        f"失败资源 {len(failed_resource_ids)} 个"),
        decision_reason="成功资源完成冻结证据判定；失败资源被隔离并转人工复核。",
        evidence_refs=[item.evidence_id for item in evidence],
        resource_ids=sorted(claims_by_resource),
        review_ids=sorted({item.review_id for item in claims}),
        step_context=step_context,
        llm_metadata=last_result.trace_metadata() if last_result else None,
    )
    return {
        "claim_judgements": [item.model_dump(mode="json") for item in judgements],
        "claim_metrics": {
            key: (value.model_dump(mode="json") if hasattr(value, "model_dump") else value)
            for key, value in metrics.items()
        },
        "claim_failed_resource_ids": sorted(failed_resource_ids),
        "claim_check_status": ClaimCheckStatus.COMPLETED.value,
        "current_node": "claim_judge",
        "trace": [trace],
        "errors": errors,
    }


def claim_decide_node(state: AgentState) -> dict[str, Any]:
    step_context = start_step(state)
    review = dict(state.get("review_result", {}))
    failed_resource_ids = set(state.get("claim_failed_resource_ids", []))
    if state.get("claim_check_status") != ClaimCheckStatus.COMPLETED.value:
        review.update({
            "decision": ReviewDecision.HUMAN_REVIEW.value,
            "status": ReviewDecision.HUMAN_REVIEW.value,
            "passed": False,
            "claim_check_status": ClaimCheckStatus.FAILED.value,
            "claim_hallucination_rate": None,
            "claim_metric_status": ClaimMetricStatus.INCOMPLETE.value,
        })
        decision = ReviewDecision.HUMAN_REVIEW
        bad = []
    else:
        claims = {item["claim_id"]: item for item in state.get("extracted_claims", [])}
        bad = [
            item for item in state.get("claim_judgements", [])
            if item.get("verdict") in {ClaimVerdict.CONTRADICTED.value, ClaimVerdict.NOT_IN_EVIDENCE.value}
        ]
        metrics = state.get("claim_metrics", {})
        incomplete = bool(failed_resource_ids) or any(
            item.get("metric_status") == ClaimMetricStatus.INCOMPLETE.value
            for item in metrics.values()
        )
        total_factual = sum(item.get("factual_claim_total", 0) for item in metrics.values())
        total_bad = sum(
            item.get("contradicted_claim_total", 0) + item.get("not_in_evidence_claim_total", 0)
            for item in metrics.values()
        )
        micro_rate = (total_bad / total_factual) if total_factual else 0.0
        metric_status = (
            ClaimMetricStatus.INCOMPLETE if incomplete else
            ClaimMetricStatus.NOT_APPLICABLE if not total_factual else
            ClaimMetricStatus.COMPLETE
        )
        review.update({
            "claim_check_status": ClaimCheckStatus.COMPLETED.value,
            "claim_total": len(claims),
            "claim_metric_status": metric_status.value,
            "claim_hallucination_rate": None if incomplete else micro_rate,
            "legacy_reviewer_score": review.get("hallucination_score"),
        })
        resources = {item.resource_id: item for item in state.get("generated_resources", [])}
        existing_issue_resources = {
            str(item.get("resource_id"))
            for item in review.get("issues", [])
            if isinstance(item, dict) and item.get("resource_id")
        }
        for resource_id in sorted(failed_resource_ids - existing_issue_resources):
            resource = resources.get(resource_id)
            if resource is None:
                continue
            review.setdefault("issues", []).append({
                "issue_id": str(uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{state.get('run_id')}:claim-audit-failed:{resource_id}",
                )),
                "code": "evidence_gap",
                "severity": "high",
                "resource_type": resource.resource_type,
                "resource_id": resource.resource_id,
                "resource_version": resource.version,
                "claim_ids": [],
                "knowledge_point": None,
                "description": "该资源的 Claim 审核未完成，需要人工复核。",
            })
        if incomplete:
            decision = ReviewDecision.HUMAN_REVIEW
        elif bad:
            decision = ReviewDecision.REVISE
            for index, judgement in enumerate(bad, start=1):
                claim = claims[judgement["claim_id"]]
                resource = resources[claim["resource_id"]]
                code = "factual_risk" if judgement["verdict"] == ClaimVerdict.CONTRADICTED.value else "evidence_gap"
                review.setdefault("issues", []).append({
                    "issue_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state.get('run_id')}:claim-issue:{judgement['claim_id']}")),
                    "code": code,
                    "severity": "high",
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "resource_version": resource.version,
                    "claim_ids": [judgement["claim_id"]],
                    "knowledge_point": claim.get("knowledge_point_id"),
                    "description": judgement["reason"],
                })
                review.setdefault("revision_instructions", []).append({
                    "instruction_id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{state.get('run_id')}:claim-instruction:{judgement['claim_id']}")),
                    "issue_codes": [code],
                    "target_resource_type": resource.resource_type,
                    "target_claim_ids": [judgement["claim_id"]],
                    "action": "依据冻结 Evidence 修正或删除该事实陈述，并重新进行 Claim 抽取与判定。",
                    "priority": index,
                })
        else:
            decision = ReviewDecision.APPROVE
        review.update({
            "decision": decision.value,
            "status": decision.value,
            "passed": decision == ReviewDecision.APPROVE,
            "claim_check_status": (
                ClaimCheckStatus.FAILED.value
                if failed_resource_ids
                else ClaimCheckStatus.COMPLETED.value
            ),
        })
    trace = build_trace_item(
        state,
        agent_name="claim_supervisor",
        action="Claim 确定性决策",
        status=StepStatus.HUMAN_REVIEW if decision == ReviewDecision.HUMAN_REVIEW else StepStatus.SUCCESS,
        input_summary=f"Claim 数：{len(state.get('extracted_claims', []))}",
        output_summary=f"决策：{decision.value}；问题 Claim：{len(bad)}",
        decision_reason="自动发布要求所有事实 Claim 完整判定且不存在 contradicted/not_in_evidence。",
        resource_ids=[item.resource_id for item in state.get("generated_resources", [])],
        review_ids=list(review.get("review_ids", {}).values()),
        step_context=step_context,
    )
    return {
        "review_result": review,
        "claim_check_status": review.get(
            "claim_check_status", state.get("claim_check_status")
        ),
        "current_node": "claim_supervisor",
        "trace": [trace],
        "errors": [],
    }
