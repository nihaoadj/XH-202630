"""Pydantic contracts shared by Agent nodes and workflow tracing."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.errors import (
    ApplicationError,
    ErrorCode,
    PUBLIC_MESSAGES,
    require_degraded_generation,
)
from app.models.knowledge import EvidenceItem, RetrievalStatus
from app.models.schemas import LearnerProfile, LearningResource
from app.models.workflow import (
    ErrorInfo,
    StepStatus,
    WORKFLOW_SCHEMA_VERSION,
)


T = TypeVar("T")


_RECORDED_STEP_CONTEXT: ContextVar[Optional[Dict[str, Any]]] = ContextVar(
    "recorded_step_context",
    default=None,
)


def bind_recorded_step_context(context: Dict[str, Any]) -> Token:
    """Bind the identity preallocated by the durable node wrapper."""

    return _RECORDED_STEP_CONTEXT.set(dict(context))


def reset_recorded_step_context(token: Token) -> None:
    _RECORDED_STEP_CONTEXT.reset(token)


class NodeResult(BaseModel, Generic[T]):
    """Validated node outcome before it is projected back into WorkflowState."""

    status: StepStatus
    output: Optional[T] = None
    error: Optional[ErrorInfo] = None

    @model_validator(mode="after")
    def validate_outcome(self) -> "NodeResult[T]":
        if self.status == StepStatus.SUCCESS and (self.output is None or self.error is not None):
            raise ValueError("success requires output and forbids error")
        if self.status == StepStatus.DEGRADED and (self.output is None or self.error is None):
            raise ValueError("degraded requires both fallback output and error")
        if self.status in {StepStatus.FAILED, StepStatus.RETRYABLE_ERROR} and (
            self.output is not None or self.error is None
        ):
            raise ValueError("failed outcomes require error and forbid output")
        return self


class AgentInput(BaseModel):
    schema_version: Literal["1.0"] = WORKFLOW_SCHEMA_VERSION
    run_id: str = "direct-node-call"


class DiagnosisInput(AgentInput):
    learner: LearnerProfile
    topic: str
    diagnostic_result_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    generation_mode: str = "standard"


class DiagnosisOutput(BaseModel):
    diagnosis: Dict[str, Any]


class RetrieverInput(AgentInput):
    topic: str
    knowledge_base_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class RetrieverOutput(BaseModel):
    retrieved_evidence: List[EvidenceItem] = Field(default_factory=list)
    retrieval_status: RetrievalStatus
    retrieval_config_hash: Optional[str] = None
    retrieval_query_hashes: List[str] = Field(default_factory=list)
    retrieval_candidate_count: int = Field(default=0, ge=0)
    retrieval_dropped_candidate_count: int = Field(default=0, ge=0)
    retrieval_partial_failure_count: int = Field(default=0, ge=0)


class PlannerInput(AgentInput):
    learner: LearnerProfile
    topic: str
    diagnostic_result_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    generation_mode: str = "standard"
    constraints: Dict[str, Any] = Field(default_factory=dict)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    retrieved_evidence: List[EvidenceItem] = Field(default_factory=list)


class PlannerOutput(BaseModel):
    learning_plan: Dict[str, Any]


class GeneratorInput(AgentInput):
    learner: LearnerProfile
    topic: str
    resource_types: List[str] = Field(min_length=1)
    target_skill_nodes: List[str] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    generation_mode: str = "standard"
    constraints: Dict[str, Any] = Field(default_factory=dict)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    retrieved_evidence: List[EvidenceItem] = Field(default_factory=list)
    learning_plan: Dict[str, Any] = Field(default_factory=dict)
    review_result: Dict[str, Any] = Field(default_factory=dict)
    generated_resources: List[LearningResource] = Field(default_factory=list)
    include_review: bool = True
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)


class GeneratorOutput(BaseModel):
    generated_resources: List[LearningResource]
    generation_attempt: int = Field(ge=1)
    revision_count: int = Field(ge=0)


class ReviewerInput(AgentInput):
    generated_resources: List[LearningResource] = Field(default_factory=list)
    retrieved_evidence: List[EvidenceItem] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)
    generation_mode: str = "standard"


class ReviewerOutput(BaseModel):
    review_result: Dict[str, Any]


class StrictLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class DiagnosisLLMOutput(StrictLLMOutput):
    ability_tags: List[str] = Field(default_factory=list, max_length=20)
    weak_points: List[str] = Field(default_factory=list, max_length=20)
    recommended_difficulty: Literal["初级", "中级", "高级"]
    suggestion: str = Field(min_length=1, max_length=2000)


class PlannedPathItem(StrictLLMOutput):
    order: int = Field(ge=1)
    topic: str = Field(min_length=1, max_length=256)
    reason: str = Field(min_length=1, max_length=2000)


class PlannerLLMOutput(StrictLLMOutput):
    learning_path: List[PlannedPathItem] = Field(min_length=1, max_length=50)
    skip_points: List[str] = Field(default_factory=list, max_length=50)
    remedial_points: List[str] = Field(default_factory=list, max_length=50)
    challenge_points: List[str] = Field(default_factory=list, max_length=50)
    resource_requirements: Dict[str, str] = Field(default_factory=dict)
    decision_reason: str = Field(min_length=1, max_length=4000)

    @field_validator("learning_path")
    @classmethod
    def validate_unique_order(cls, items: List[PlannedPathItem]) -> List[PlannedPathItem]:
        orders = [item.order for item in items]
        if len(orders) != len(set(orders)):
            raise ValueError("learning_path order must be unique")
        return items


class GeneratedResourceDraft(StrictLLMOutput):
    resource_type: str = Field(min_length=1, max_length=64)
    difficulty: str = Field(min_length=1, max_length=32)
    content_text: str = Field(min_length=1, max_length=40000)
    knowledge_points: List[str] = Field(min_length=1, max_length=50)


class GeneratedResourceBatch(StrictLLMOutput):
    resources: List[GeneratedResourceDraft] = Field(min_length=1, max_length=10)

    @field_validator("resources")
    @classmethod
    def validate_unique_resource_types(
        cls,
        resources: List[GeneratedResourceDraft],
    ) -> List[GeneratedResourceDraft]:
        resource_types = [resource.resource_type for resource in resources]
        if len(resource_types) != len(set(resource_types)):
            raise ValueError("resource_type must be unique")
        return resources


class ReviewIssue(StrictLLMOutput):
    code: Literal[
        "factual_risk",
        "evidence_gap",
        "procedure_error",
        "difficulty_mismatch",
        "coverage_gap",
        "structure_quality",
        "other",
    ]
    severity: Literal["low", "medium", "high", "critical"]
    resource_type: Optional[str] = Field(default=None, min_length=1, max_length=64)
    resource_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    resource_version: Optional[int] = Field(default=None, ge=1)
    claim_ids: List[str] = Field(default_factory=list, max_length=100)
    knowledge_point: Optional[str] = Field(default=None, min_length=1, max_length=256)
    description: str = Field(min_length=1, max_length=2000)


class RevisionInstruction(StrictLLMOutput):
    issue_codes: List[str] = Field(min_length=1, max_length=20)
    target_resource_type: str = Field(min_length=1, max_length=64)
    target_claim_ids: List[str] = Field(default_factory=list, max_length=100)
    action: str = Field(min_length=1, max_length=4000)
    priority: int = Field(default=1, ge=1, le=100)


class ReviewLLMOutput(StrictLLMOutput):
    decision: Literal["approve", "revise", "reject", "human_review"]
    hallucination_score: float = Field(ge=0.0, le=1.0)
    issues: List[ReviewIssue] = Field(default_factory=list, max_length=100)
    difficulty_match: bool
    coverage_rate: float = Field(ge=0.0, le=1.0)
    suggestion: str = Field(min_length=1, max_length=4000)
    revision_instructions: List[RevisionInstruction] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_decision_payload(self) -> "ReviewLLMOutput":
        if self.decision == "revise" and not self.revision_instructions:
            raise ValueError("revise requires revision_instructions")
        if self.decision == "approve" and self.revision_instructions:
            raise ValueError("approve forbids revision_instructions")
        return self


def make_error_info(
    code: ErrorCode | str,
    *,
    source: str,
    attempt: int = 1,
    category: str = "upstream",
    retryable: bool = False,
    safe_detail: Optional[str] = None,
) -> ErrorInfo:
    normalized = code.value if isinstance(code, ErrorCode) else str(code)
    try:
        message = PUBLIC_MESSAGES.get(ErrorCode(normalized), "工作流步骤执行失败")
    except ValueError:
        message = "工作流步骤执行失败"
    return ErrorInfo(
        code=normalized,
        category=category,
        message=message,
        retryable=retryable,
        source=source,
        attempt=attempt,
        safe_detail=safe_detail,
    )


def require_agent_fallback(
    state: Dict[str, Any],
    error: ErrorInfo,
) -> ErrorInfo:
    """Apply the global degraded policy while making strict mode fail closed."""

    try:
        code = ErrorCode(error.code)
    except ValueError:
        code = ErrorCode.LLM_UPSTREAM_UNAVAILABLE
    if state.get("generation_mode", "standard") == "strict":
        raise ApplicationError(code)
    require_degraded_generation(code)
    return error


def start_step(
    state: Dict[str, Any],
    *,
    attempt: Optional[int] = None,
) -> Dict[str, Any]:
    """Allocate step identity and start time before a node performs work."""

    recorded = _RECORDED_STEP_CONTEXT.get()
    if recorded is not None:
        context = dict(recorded)
        if attempt is not None:
            context["attempt"] = attempt
        return context

    return {
        "step_id": str(uuid.uuid4()),
        "sequence": len(state.get("trace", [])) + 1,
        "attempt": attempt or state.get("generation_attempt", 1),
        "started_at": datetime.now(timezone.utc),
    }


def workflow_budget_metadata(
    state: Dict[str, Any],
    entered_at: datetime,
) -> Dict[str, int]:
    """Return safe global-deadline timing captured at node entry."""

    started_at = state.get("workflow_started_at")
    deadline_at = state.get("workflow_deadline_at")
    if not isinstance(started_at, datetime) or not isinstance(deadline_at, datetime):
        return {}
    return {
        "workflow_elapsed_ms": max(0, int((entered_at - started_at).total_seconds() * 1000)),
        "workflow_remaining_ms": max(0, int((deadline_at - entered_at).total_seconds() * 1000)),
    }


def build_trace_item(
    state: Dict[str, Any],
    *,
    agent_name: str,
    action: str,
    status: StepStatus | str,
    input_summary: str,
    output_summary: str,
    decision_reason: str,
    evidence_refs: Optional[List[str]] = None,
    resource_ids: Optional[List[str]] = None,
    review_ids: Optional[List[str]] = None,
    error: Optional[ErrorInfo] = None,
    attempt: Optional[int] = None,
    step_context: Optional[Dict[str, Any]] = None,
    llm_metadata: Optional[Dict[str, Any]] = None,
    retrieval_metadata: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Create a complete trace item before the node result leaves the node."""

    context = step_context or start_step(state, attempt=attempt)
    now = datetime.now(timezone.utc)
    started_at = context["started_at"]
    duration_ms = max(0, int((now - started_at).total_seconds() * 1000))
    normalized_status = status.value if isinstance(status, StepStatus) else status
    item = {
        "schema_version": state.get("schema_version", WORKFLOW_SCHEMA_VERSION),
        "run_id": state.get("run_id") or "direct-node-call",
        "step_id": context["step_id"],
        "sequence": context["sequence"],
        "agent_name": agent_name,
        "node_name": context.get("node_name", agent_name),
        "action": action,
        "attempt": context["attempt"],
        "status": normalized_status,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "decision_reason": decision_reason,
        "evidence_refs": evidence_refs or [],
        "resource_ids": resource_ids or [],
        "review_ids": review_ids or [],
        "retry_count": (llm_metadata or {}).get("retry_count", 0),
        "error_code": error.code if error else None,
        "error_message": error.message if error else None,
        "error": error.model_dump(mode="json") if error else None,
        "timestamp": started_at.isoformat(),
        "started_at": started_at.isoformat(),
        "ended_at": now.isoformat(),
        "duration_ms": duration_ms,
    }
    if llm_metadata:
        item.update(llm_metadata)
    if retrieval_metadata:
        item.update(retrieval_metadata)
    item.update(workflow_budget_metadata(state, started_at))
    return item
