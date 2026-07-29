"""LangGraph topology and workflow-level control semantics."""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, StateGraph

from app.agents.diagnosis import diagnose_node
from app.agents.generator import generate_node
from app.agents.planner import plan_node
from app.agents.retriever import retrieve_node
from app.agents.reviewer import review_node
from app.agents.state import AgentState
from app.core.errors import ErrorCode
from app.models.agent_contracts import build_trace_item, make_error_info, start_step
from app.models.schemas import LearningResource
from app.models.workflow import (
    ClaimCheckStatus,
    ResourceStatus,
    ReviewDecision,
    StepStatus,
    WorkflowStatus,
)


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


def build_workflow():
    """Build the synchronous P0-01 Agent workflow."""
    workflow = StateGraph(AgentState)

    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("plan", plan_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("review", review_node)
    workflow.add_node("prepare_revision", prepare_revision_node)
    workflow.add_node("finalize_draft", finalize_draft_node)
    workflow.add_node("claim_check", claim_check_node)
    workflow.add_node("finalize", decide_node)

    workflow.set_entry_point("diagnose")
    workflow.add_edge("diagnose", "retrieve")
    workflow.add_edge("retrieve", "plan")
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

    return workflow.compile()
