"""LangGraph topology and workflow-level control semantics."""

from __future__ import annotations

from functools import partial
from inspect import signature
from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.diagnosis import diagnose_node
from app.agents.generator import generate_node
from app.agents.planner import plan_node
from app.agents.retriever import retrieve_node
from app.agents.reviewer import review_node
from app.agents.state import AgentState
from app.core.errors import ErrorCode
from app.core.evidence_retriever import (
    EvidenceRetriever,
    default_evidence_retriever,
    retrieval_policy_from_settings,
)
from app.config import get_settings
from app.core.llm_gateway import LLMGateway, default_llm_gateway
from app.models.agent_contracts import build_trace_item, make_error_info, start_step
from app.models.schemas import LearningResource
from app.models.workflow import (
    ClaimCheckStatus,
    ResourceStatus,
    ReviewDecision,
    StepStatus,
    WorkflowStatus,
)
from app.models.knowledge import RetrievalStatus


def _review_decision(state: AgentState) -> ReviewDecision:
    review = state.get("review_result", {})
    raw_decision = review.get("decision")
    if raw_decision in {item.value for item in ReviewDecision}:
        return ReviewDecision(raw_decision)
    if review.get("passed", False) and review.get("hallucination_score", 1.0) < 0.2:
        return ReviewDecision.APPROVE
    return ReviewDecision.REVISE


def _resource_copies(
    resources: list[LearningResource],
    status: ResourceStatus,
) -> list[LearningResource]:
    return [resource.model_copy(update={"review_status": status.value}) for resource in resources]


def _has_degradation(state: AgentState) -> bool:
    return bool(state.get("errors")) or any(
        item.get("status") == StepStatus.DEGRADED.value
        for item in state.get("trace", [])
        if isinstance(item, dict)
    )


def route_after_generate(state: AgentState) -> str:
    if state.get("include_review", True):
        return "review"
    if state.get("include_claim_check", False):
        return "claim_check"
    return "finalize_draft"


def _evidence_gate_passes(state: AgentState) -> bool:
    evidence = state.get("retrieved_evidence", [])
    policy = retrieval_policy_from_settings(get_settings())
    if (
        state.get("retrieval_status") != RetrievalStatus.AVAILABLE.value
        or len(evidence) < policy.min_evidence_count
    ):
        return False
    knowledge_base_id = state.get("knowledge_base_id")
    evidence_ids = [item.evidence_id for item in evidence]
    chunk_ids = [item.chunk_id for item in evidence]
    ranks = [item.rank for item in evidence]
    return (
        all(item.knowledge_base_id == knowledge_base_id for item in evidence)
        and all(item.normalized_score >= policy.min_normalized_score for item in evidence)
        and len(evidence_ids) == len(set(evidence_ids))
        and len(chunk_ids) == len(set(chunk_ids))
        and len(ranks) == len(set(ranks))
    )


def evidence_gate_node(state: AgentState) -> dict[str, Any]:
    """Fail closed before any planning or factual generation LLM call."""

    step_context = start_step(state)
    passed = _evidence_gate_passes(state)
    status = state.get("retrieval_status", RetrievalStatus.PENDING.value)
    evidence = state.get("retrieved_evidence", [])
    error = None
    errors: list[dict[str, Any]] = []
    if not passed:
        existing_codes = {
            item.get("code") for item in state.get("errors", []) if isinstance(item, dict)
        }
        if status == RetrievalStatus.NO_HIT.value or not existing_codes:
            error = make_error_info(
                ErrorCode.EVIDENCE_INSUFFICIENT,
                source="evidence_gate",
                category="evidence",
                safe_detail=f"retrieval_status:{status}",
            )
            errors.append(error.model_dump(mode="json"))
    trace_item = build_trace_item(
        state,
        agent_name="evidence_gate",
        action="事实生成证据门禁",
        status=StepStatus.SUCCESS if passed else StepStatus.HUMAN_REVIEW,
        input_summary=f"检索状态：{status}；证据数：{len(evidence)}",
        output_summary="门禁通过" if passed else "证据不足，禁止事实生成",
        decision_reason=(
            "检索结果具有唯一证据、Chunk、rank，且全部属于请求知识库。"
            if passed
            else "事实型资源至少需要一条通过来源与知识库边界校验的证据。"
        ),
        evidence_refs=[item.evidence_id for item in evidence],
        error=error,
        step_context=step_context,
        retrieval_metadata={
            "retrieval_status": status,
            "retrieval_config_hash": state.get("retrieval_config_hash"),
            "retrieval_query_hashes": state.get("retrieval_query_hashes", []),
            "retrieval_candidate_count": state.get("retrieval_candidate_count", 0),
            "retrieval_dropped_candidate_count": state.get(
                "retrieval_dropped_candidate_count", 0
            ),
            "retrieval_partial_failure_count": state.get(
                "retrieval_partial_failure_count", 0
            ),
            "retrieval_query_count": len(state.get("retrieval_query_hashes", [])),
            "retrieval_evidence_count": len(evidence),
            "retrieval_dropped_count": state.get(
                "retrieval_dropped_candidate_count", 0
            ),
        },
    )
    return {
        "current_node": "evidence_gate",
        "trace": [trace_item],
        "errors": errors,
    }


def route_after_evidence_gate(state: AgentState) -> str:
    return "plan" if _evidence_gate_passes(state) else "finalize_evidence_insufficient"


def finalize_evidence_insufficient_node(state: AgentState) -> dict[str, Any]:
    step_context = start_step(state)
    status = state.get("retrieval_status", RetrievalStatus.EVIDENCE_INSUFFICIENT.value)
    trace_item = build_trace_item(
        state,
        agent_name="supervisor",
        action="证据不足终结",
        status=StepStatus.HUMAN_REVIEW,
        input_summary=(
            f"检索状态：{status}；证据数：{len(state.get('retrieved_evidence', []))}"
        ),
        output_summary="未生成任何事实资源，转人工复核",
        decision_reason="证据门禁未通过；空证据不得进入 Planner、Generator 或 Reviewer。",
        evidence_refs=[],
        step_context=step_context,
        retrieval_metadata={
            "retrieval_status": status,
            "retrieval_config_hash": state.get("retrieval_config_hash"),
            "retrieval_query_hashes": state.get("retrieval_query_hashes", []),
            "retrieval_candidate_count": state.get("retrieval_candidate_count", 0),
            "retrieval_dropped_candidate_count": state.get(
                "retrieval_dropped_candidate_count", 0
            ),
            "retrieval_partial_failure_count": state.get(
                "retrieval_partial_failure_count", 0
            ),
            "retrieval_query_count": len(state.get("retrieval_query_hashes", [])),
            "retrieval_evidence_count": len(state.get("retrieved_evidence", [])),
            "retrieval_dropped_count": state.get(
                "retrieval_dropped_candidate_count", 0
            ),
        },
    )
    return {
        "generated_resources": [],
        "review_result": {
            "decision": ReviewDecision.HUMAN_REVIEW.value,
            "status": ReviewDecision.HUMAN_REVIEW.value,
            "claim_check_status": ClaimCheckStatus.NOT_REQUESTED.value,
            "review_ids": {},
            "issues": ["当前知识证据不足，未生成事实资源"],
        },
        "claim_check_status": ClaimCheckStatus.NOT_REQUESTED.value,
        "workflow_status": WorkflowStatus.HUMAN_REVIEW.value,
        "final_decision": "证据不足，未生成事实资源",
        "current_node": "finalize_evidence_insufficient",
        "trace": [trace_item],
        "errors": [],
    }


def route_after_review(state: AgentState) -> str:
    decision = _review_decision(state)
    if decision == ReviewDecision.REVISE:
        if state.get("revision_count", 0) < state.get("max_iterations", 2):
            return "prepare_revision"
        return "claim_check" if state.get("include_claim_check", False) else "finalize"
    if state.get("include_claim_check", False):
        return "claim_check"
    return "finalize"


def decide_next(state: AgentState) -> str:
    """Compatibility router retained for existing callers and tests."""
    if _review_decision(state) != ReviewDecision.REVISE:
        return "decide"
    revision_count = state.get("revision_count", state.get("iteration", 0))
    return "generate" if revision_count < state.get("max_iterations", 2) else "decide"


def prepare_revision_node(state: AgentState) -> dict[str, Any]:
    revision_count = state.get("revision_count", 0) + 1
    generation_attempt = revision_count + 1
    step_context = start_step(state, attempt=generation_attempt)
    review = state.get("review_result", {})
    trace_item = build_trace_item(
        state,
        agent_name="supervisor",
        action="准备返工",
        status=StepStatus.SUCCESS,
        input_summary=f"审核决策：{review.get('decision', 'revise')}；已返工：{revision_count - 1}",
        output_summary=f"进入第 {generation_attempt} 次生成（第 {revision_count} 次返工）",
        decision_reason=review.get("suggestion") or "审核要求修改且仍有业务返工额度。",
        resource_ids=[resource.resource_id for resource in state.get("generated_resources", [])],
        attempt=generation_attempt,
        step_context=step_context,
    )
    return {
        "revision_count": revision_count,
        "generation_attempt": generation_attempt,
        "current_node": "prepare_revision",
        "trace": [trace_item],
        "errors": [],
    }


def finalize_draft_node(state: AgentState) -> dict[str, Any]:
    step_context = start_step(state)
    resources = _resource_copies(
        state.get("generated_resources", []),
        ResourceStatus.UNREVIEWED_DRAFT,
    )
    workflow_status = (
        WorkflowStatus.DEGRADED if _has_degradation(state) else WorkflowStatus.COMPLETED
    )
    review = {
        "decision": ReviewDecision.NOT_REQUESTED.value,
        "status": ReviewDecision.NOT_REQUESTED.value,
        "claim_check_status": ClaimCheckStatus.NOT_REQUESTED.value,
        "review_ids": {},
        "revision_count": state.get("revision_count", 0),
        "issues": [],
    }
    trace_item = build_trace_item(
        state,
        agent_name="supervisor",
        action="草稿终结",
        status=StepStatus.DEGRADED if workflow_status == WorkflowStatus.DEGRADED else StepStatus.SUCCESS,
        input_summary="include_review=false；include_claim_check=false",
        output_summary="资源以未审核草稿状态返回",
        decision_reason="调用方明确关闭审核，资源不得标记为已批准。",
        resource_ids=[resource.resource_id for resource in resources],
        step_context=step_context,
    )
    return {
        "generated_resources": resources,
        "review_result": review,
        "claim_check_status": ClaimCheckStatus.NOT_REQUESTED.value,
        "workflow_status": workflow_status.value,
        "final_decision": "未审核草稿",
        "current_node": "finalize_draft",
        "trace": [trace_item],
        "errors": [],
    }


def claim_check_node(state: AgentState) -> dict[str, Any]:
    """Explicit P0-06 capability placeholder; never reports a false pass."""
    step_context = start_step(state)
    error = make_error_info(
        ErrorCode.CLAIM_CHECK_NOT_IMPLEMENTED,
        source="claim_checker",
        attempt=state.get("generation_attempt", 1),
        category="capability",
    )
    review = dict(state.get("review_result", {}))
    review.update({
        "claim_check_status": ClaimCheckStatus.UNAVAILABLE.value,
        "claims": [],
    })
    if not state.get("include_review", True):
        review.update({
            "decision": ReviewDecision.NOT_REQUESTED.value,
            "status": ReviewDecision.NOT_REQUESTED.value,
            "review_ids": {},
        })
        resource_status = ResourceStatus.UNREVIEWED_DRAFT
        workflow_status = WorkflowStatus.HUMAN_REVIEW
        final_decision = "Claim 审核不可用，需人工复核"
    else:
        review_decision = _review_decision(state)
        if review_decision == ReviewDecision.REJECT:
            resource_status = ResourceStatus.REJECTED
            workflow_status = WorkflowStatus.FAILED
            final_decision = "审核拒绝；Claim 审核能力不可用"
        else:
            resource_status = ResourceStatus.HUMAN_REVIEW
            workflow_status = WorkflowStatus.HUMAN_REVIEW
            final_decision = "Claim 审核不可用，需人工复核"

    resources = _resource_copies(state.get("generated_resources", []), resource_status)
    trace_item = build_trace_item(
        state,
        agent_name="claim_checker",
        action="Claim 级审核",
        status=(
            StepStatus.FAILED
            if workflow_status == WorkflowStatus.FAILED
            else StepStatus.HUMAN_REVIEW
        ),
        input_summary=f"请求 Claim 审核；资源数：{len(resources)}",
        output_summary="Claim 审核能力尚未启用，转人工复核",
        decision_reason="P0-06 能力未接入，不能以空 Claim 列表代表审核通过。",
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review.get("review_ids", {}).values()),
        error=error,
        step_context=step_context,
    )
    return {
        "generated_resources": resources,
        "review_result": review,
        "claim_check_status": ClaimCheckStatus.UNAVAILABLE.value,
        "workflow_status": workflow_status.value,
        "final_decision": final_decision,
        "current_node": "claim_check",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")],
    }


def decide_node(state: AgentState) -> dict[str, Any]:
    """Finalize review semantics without silently approving risky output."""
    step_context = start_step(state)
    review = dict(state.get("review_result", {}))
    decision = _review_decision(state)
    strict_with_degradation = state.get("generation_mode") == "strict" and _has_degradation(state)

    if decision == ReviewDecision.APPROVE and not strict_with_degradation:
        resource_status = ResourceStatus.APPROVED
        workflow_status = (
            WorkflowStatus.DEGRADED if _has_degradation(state) else WorkflowStatus.COMPLETED
        )
        final_decision = "审核通过"
    elif decision == ReviewDecision.REJECT:
        resource_status = ResourceStatus.REJECTED
        workflow_status = WorkflowStatus.FAILED
        final_decision = "审核拒绝"
    else:
        resource_status = ResourceStatus.HUMAN_REVIEW
        workflow_status = WorkflowStatus.HUMAN_REVIEW
        final_decision = (
            "严格模式下存在降级结果，需人工复核"
            if strict_with_degradation
            else "返工额度已用尽或审核无法自动决策，需人工复核"
        )

    review["claim_check_status"] = ClaimCheckStatus.NOT_REQUESTED.value
    review["revision_count"] = state.get("revision_count", 0)
    resources = _resource_copies(state.get("generated_resources", []), resource_status)
    trace_status = (
        StepStatus.HUMAN_REVIEW
        if workflow_status == WorkflowStatus.HUMAN_REVIEW
        else StepStatus.FAILED
        if workflow_status == WorkflowStatus.FAILED
        else StepStatus.DEGRADED
        if workflow_status == WorkflowStatus.DEGRADED
        else StepStatus.SUCCESS
    )
    trace_item = build_trace_item(
        state,
        agent_name="supervisor",
        action="协同决策",
        status=trace_status,
        input_summary=f"审核决策：{decision.value}；返工次数：{state.get('revision_count', 0)}/{state.get('max_iterations', 2)}",
        output_summary=f"最终决策：{final_decision}",
        decision_reason="综合审核结论、降级状态和业务返工额度确定资源终态。",
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review.get("review_ids", {}).values()),
        step_context=step_context,
    )
    return {
        "generated_resources": resources,
        "review_result": review,
        "claim_check_status": ClaimCheckStatus.NOT_REQUESTED.value,
        "workflow_status": workflow_status.value,
        "final_decision": final_decision,
        "current_node": "supervisor",
        "trace": [trace_item],
        "errors": [],
    }


def _bind_llm_gateway(node, gateway: LLMGateway):
    """Bind production Agent nodes while keeping pure workflow test doubles simple."""

    if "llm_gateway" not in signature(node).parameters:
        return node
    return partial(node, llm_gateway=gateway)


def _bind_evidence_retriever(node, retriever: EvidenceRetriever):
    if "evidence_retriever" not in signature(node).parameters:
        return node
    return partial(node, evidence_retriever=retriever)


def build_workflow(
    llm_gateway: LLMGateway | None = None,
    evidence_retriever: EvidenceRetriever | None = None,
):
    """Build the synchronous workflow with the P0-03 evidence boundary."""
    gateway = llm_gateway or default_llm_gateway()
    retriever = evidence_retriever or default_evidence_retriever()
    workflow = StateGraph(AgentState)

    workflow.add_node("diagnose", _bind_llm_gateway(diagnose_node, gateway))
    workflow.add_node("retrieve", _bind_evidence_retriever(retrieve_node, retriever))
    workflow.add_node("evidence_gate", evidence_gate_node)
    workflow.add_node("plan", _bind_llm_gateway(plan_node, gateway))
    workflow.add_node("generate", _bind_llm_gateway(generate_node, gateway))
    workflow.add_node("review", _bind_llm_gateway(review_node, gateway))
    workflow.add_node("prepare_revision", prepare_revision_node)
    workflow.add_node("finalize_draft", finalize_draft_node)
    workflow.add_node("claim_check", claim_check_node)
    workflow.add_node("finalize", decide_node)
    workflow.add_node(
        "finalize_evidence_insufficient",
        finalize_evidence_insufficient_node,
    )

    workflow.set_entry_point("diagnose")
    workflow.add_edge("diagnose", "retrieve")
    workflow.add_edge("retrieve", "evidence_gate")
    workflow.add_conditional_edges(
        "evidence_gate",
        route_after_evidence_gate,
        {
            "plan": "plan",
            "finalize_evidence_insufficient": "finalize_evidence_insufficient",
        },
    )
    workflow.add_edge("plan", "generate")
    workflow.add_conditional_edges(
        "generate",
        route_after_generate,
        {
            "review": "review",
            "claim_check": "claim_check",
            "finalize_draft": "finalize_draft",
        },
    )
    workflow.add_conditional_edges(
        "review",
        route_after_review,
        {
            "prepare_revision": "prepare_revision",
            "claim_check": "claim_check",
            "finalize": "finalize",
        },
    )
    workflow.add_edge("prepare_revision", "generate")
    workflow.add_edge("finalize_draft", END)
    workflow.add_edge("claim_check", END)
    workflow.add_edge("finalize", END)
    workflow.add_edge("finalize_evidence_insufficient", END)

    return workflow.compile()
