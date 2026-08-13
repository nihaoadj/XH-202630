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
    resources = state.get("generated_resources", [])
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
    payload = {
        "allowed_evidence": [
            {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
            for item in evidence
        ],
        "allowed_knowledge_point_ids": state.get("target_skill_nodes", []),
        "resources": [
            {
                "resource_id": item.resource_id,
                "resource_version": item.version,
                "content_text": item.content_text,
            }
            for item in resources
        ],
    }
    try:
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
        batch_ids = [item.resource_id for item in batches]
        if len(batch_ids) != len(set(batch_ids)) or set(batch_ids) != set(review_ids):
            raise ValueError("extractor resource set mismatch")
        by_resource = {item.resource_id: item.claims for item in batches}
        if any(not by_resource[item.resource_id] for item in resources):
            raise ValueError("each non-empty resource requires at least one claim")
        claims: list[ClaimRecord] = []
        allowed_evidence = {item.evidence_id for item in evidence}
        allowed_nodes = set(state.get("target_skill_nodes", []))
        for resource in resources:
            claims.extend(materialize_claims(
                candidates=by_resource[resource.resource_id],
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
    except LLMGatewayError as exc:
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail="llm gateway failure",
            llm_error=exc,
        )
    except (ValueError, KeyError) as exc:
        return _failure(
            state,
            node_name="claim_extractor",
            code=ErrorCode.CLAIM_EXTRACTION_INVALID,
            detail=str(exc),
        )
    trace = build_trace_item(
        state,
        agent_name="claim_extractor",
        action="独立 Claim 抽取",
        status=StepStatus.SUCCESS,
        input_summary=f"资源数：{len(resources)}；冻结证据数：{len(evidence)}",
        output_summary=f"已抽取 {len(claims)} 条 Claim",
        decision_reason="抽取结果的资源、原文跨度、知识点和 Evidence ID 已通过白名单校验。",
        evidence_refs=[item.evidence_id for item in evidence],
        resource_ids=[item.resource_id for item in resources],
        review_ids=list(review_ids.values()),
        step_context=step_context,
        llm_metadata=result.trace_metadata(),
    )
    return {
        "extracted_claims": [item.model_dump(mode="json") for item in claims],
        "claim_check_status": ClaimCheckStatus.PENDING.value,
        "current_node": "claim_extractor",
        "trace": [trace],
        "errors": [],
    }


def claim_judge_node(state: AgentState, *, llm_gateway: LLMGateway) -> dict[str, Any]:
    step_context = start_step(state)
    try:
        claims = [ClaimRecord.model_validate(item) for item in state.get("extracted_claims", [])]
        if not claims:
            raise ValueError("no validated claims")
        evidence = state.get("retrieved_evidence", [])
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
                for item in claims
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
        judgements = materialize_judgements(
            claims=claims,
            candidates=result.output.judgements,
            allowed_evidence_ids={item.evidence_id for item in evidence},
            judge_prompt_version=JUDGE_PROMPT_VERSION,
            judge_model=result.model_name,
        )
        claims_by_resource: dict[str, list[ClaimRecord]] = defaultdict(list)
        judgements_by_resource: dict[str, list] = defaultdict(list)
        for item in claims:
            claims_by_resource[item.resource_id].append(item)
        for item in judgements:
            judgements_by_resource[item.resource_id].append(item)
        metrics = {
            resource_id: compute_claim_metric(items, judgements_by_resource[resource_id])
            for resource_id, items in claims_by_resource.items()
        }
    except LLMGatewayError as exc:
        return _failure(
            state,
            node_name="claim_judge",
            code=ErrorCode.CLAIM_JUDGEMENT_INVALID,
            detail="llm gateway failure",
            llm_error=exc,
        )
    except (ValueError, KeyError) as exc:
        return _failure(
            state,
            node_name="claim_judge",
            code=ErrorCode.CLAIM_JUDGEMENT_INVALID,
            detail=str(exc),
        )
    trace = build_trace_item(
        state,
        agent_name="claim_judge",
        action="冻结证据 Claim 判定",
        status=StepStatus.SUCCESS,
        input_summary=f"Claim 数：{len(claims)}；冻结证据数：{len(evidence)}",
        output_summary=f"完成 {len(judgements)} 条独立判定",
        decision_reason="每条 Claim 恰有一个判定，Evidence ID 与当前 Run 冻结快照一致。",
        evidence_refs=[item.evidence_id for item in evidence],
        resource_ids=sorted(claims_by_resource),
        review_ids=sorted({item.review_id for item in claims}),
        step_context=step_context,
        llm_metadata=result.trace_metadata(),
    )
    return {
        "claim_judgements": [item.model_dump(mode="json") for item in judgements],
        "claim_metrics": {key: value.model_dump(mode="json") for key, value in metrics.items()},
        "claim_check_status": ClaimCheckStatus.COMPLETED.value,
        "current_node": "claim_judge",
        "trace": [trace],
        "errors": [],
    }


def claim_decide_node(state: AgentState) -> dict[str, Any]:
    step_context = start_step(state)
    review = dict(state.get("review_result", {}))
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
        incomplete = any(item.get("metric_status") == ClaimMetricStatus.INCOMPLETE.value for item in metrics.values())
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
        if incomplete:
            decision = ReviewDecision.HUMAN_REVIEW
        elif bad:
            decision = ReviewDecision.REVISE
            resources = {item.resource_id: item for item in state.get("generated_resources", [])}
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
        review.update({"decision": decision.value, "status": decision.value, "passed": decision == ReviewDecision.APPROVE})
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
        "current_node": "claim_supervisor",
        "trace": [trace],
        "errors": [],
    }
