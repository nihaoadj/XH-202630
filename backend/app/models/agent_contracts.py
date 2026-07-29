"""Pydantic contracts shared by Agent nodes and workflow tracing."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, Field, model_validator

from app.core.errors import ErrorCode, PUBLIC_MESSAGES
from app.models.schemas import LearnerProfile, LearningResource
from app.models.workflow import (
    ErrorInfo,
    StepStatus,
    WORKFLOW_SCHEMA_VERSION,
)


T = TypeVar("T")


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


class DiagnosisOutput(BaseModel):
    diagnosis: Dict[str, Any]


class RetrieverInput(AgentInput):
    topic: str
    knowledge_base_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    constraints: Dict[str, Any] = Field(default_factory=dict)


class RetrieverOutput(BaseModel):
    retrieved_chunks: List[Dict[str, Any]]
    retrieval_status: str


class PlannerInput(AgentInput):
    learner: LearnerProfile
    topic: str
    diagnostic_result_id: Optional[str] = None
    target_skill_nodes: List[str] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    generation_mode: str = "standard"
    constraints: Dict[str, Any] = Field(default_factory=dict)
    diagnosis: Dict[str, Any] = Field(default_factory=dict)
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)


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
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
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
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    difficulty_preference: Optional[str] = None
    constraints: Dict[str, Any] = Field(default_factory=dict)
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)


class ReviewerOutput(BaseModel):
    review_result: Dict[str, Any]


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


def start_step(
    state: Dict[str, Any],
    *,
    attempt: Optional[int] = None,
) -> Dict[str, Any]:
    """Allocate step identity and start time before a node performs work."""

    return {
        "step_id": str(uuid.uuid4()),
        "sequence": len(state.get("trace", [])) + 1,
        "attempt": attempt or state.get("generation_attempt", 1),
        "started_at": datetime.now(timezone.utc),
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
        "node_name": agent_name,
        "action": action,
        "attempt": context["attempt"],
        "status": normalized_status,
        "input_summary": input_summary,
        "output_summary": output_summary,
        "decision_reason": decision_reason,
        "evidence_refs": evidence_refs or [],
        "resource_ids": resource_ids or [],
        "review_ids": review_ids or [],
        "retry_count": 0,
        "error_code": error.code if error else None,
        "error_message": error.message if error else None,
        "error": error.model_dump(mode="json") if error else None,
        "timestamp": started_at.isoformat(),
        "started_at": started_at.isoformat(),
        "ended_at": now.isoformat(),
        "duration_ms": duration_ms,
    }
    return item
