"""Pydantic contracts shared by Agent nodes and workflow tracing."""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token
from datetime import datetime, timezone
from typing import Any, Dict, Generic, List, Literal, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.security.errors import (
    ApplicationError,
    ErrorCode,
    PUBLIC_MESSAGES,
    require_degraded_generation,
)
from app.models.knowledge.knowledge import EvidenceItem, RetrievalStatus
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.shared.workflow import (
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
    batch_id: str = "direct-node-call"


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


class StrictLLMOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


ResourceRepresentation = Literal["text"]


class ResourceRepresentationSpec(BaseModel):
    """Frozen execution definition for one representation of a resource spec."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    representation: ResourceRepresentation
    max_output_tokens: int = Field(ge=256, le=65536)
    display_order: int = Field(default=1, ge=1, le=100)


class ResourceSpec(BaseModel):
    """Immutable, evidence-scoped semantic resource work item."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    schema_version: Literal["1.0"] = WORKFLOW_SCHEMA_VERSION
    resource_spec_id: str = Field(min_length=36, max_length=36)
    resource_family_id: str = Field(min_length=36, max_length=36)
    resource_type: str = Field(min_length=1, max_length=64)
    learning_objective: str = Field(min_length=1, max_length=4000)
    knowledge_points: List[str] = Field(min_length=1, max_length=50)
    evidence_ids: List[str] = Field(min_length=1, max_length=100)
    difficulty: str = Field(min_length=1, max_length=32)
    representations: List[ResourceRepresentationSpec] = Field(min_length=1, max_length=1)
    dependencies: List[str] = Field(default_factory=list, max_length=20)
    display_order: int = Field(ge=1, le=100)

    @field_validator("resource_spec_id", "resource_family_id")
    @classmethod
    def validate_uuid(cls, value: str) -> str:
        try:
            parsed = uuid.UUID(value)
        except (TypeError, ValueError, AttributeError):
            raise ValueError("resource identity must be a UUID") from None
        if str(parsed) != value.lower():
            raise ValueError("resource identity must use canonical UUID form")
        return value.lower()

    @field_validator("knowledge_points", "evidence_ids", "dependencies")
    @classmethod
    def validate_unique_values(cls, values: List[str]) -> List[str]:
        if any(not value.strip() for value in values):
            raise ValueError("resource spec lists cannot contain blank values")
        if len(values) != len(set(values)):
            raise ValueError("resource spec lists must contain unique values")
        return values

    @model_validator(mode="after")
    def validate_representations(self) -> "ResourceSpec":
        representations = [item.representation for item in self.representations]
        if len(representations) != len(set(representations)):
            raise ValueError("representation must be unique within a resource spec")
        if self.resource_spec_id in self.dependencies:
            raise ValueError("resource spec cannot depend on itself")
        if representations != ["text"]:
            raise ValueError(
                f"{self.resource_type} requires a supported representation order"
            )
        return self


class ResourceGenerationContext(BaseModel):
    """Bounded context visible to one resource Agent invocation."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["1.0"] = WORKFLOW_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=128)
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = Field(min_length=1, max_length=512)
    learner_profile_summary: Dict[str, Any] = Field(default_factory=dict)
    learning_path: List[Dict[str, Any]] = Field(default_factory=list, max_length=50)
    evidence: List[EvidenceItem] = Field(min_length=1, max_length=100)
    continuation_context: List[Dict[str, Any]] = Field(default_factory=list, max_length=20)
    constraints: Dict[str, Any] = Field(default_factory=dict)
    generation_attempt: int = Field(default=1, ge=1)
    workflow_deadline_at: Optional[datetime] = None

    @field_validator("evidence")
    @classmethod
    def validate_unique_evidence(cls, values: List[EvidenceItem]) -> List[EvidenceItem]:
        evidence_ids = [item.evidence_id for item in values]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ValueError("generation context evidence_id must be unique")
        return values


class ResourceArtifactMetadata(BaseModel):
    """Server-owned routing and lineage metadata attached after LLM validation."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    resource_spec_id: str
    resource_family_id: str
    resource_type: str
    representation: ResourceRepresentation
    agent_name: str
    prompt_version: str
    artifact_format: Literal["markdown", "json"]
    validation_status: Literal["validated", "validated_with_repairs"] = "validated"
    source_evidence_ids: List[str] = Field(default_factory=list)


class GeneratedArtifact(BaseModel):
    """Uniform output consumed by the resource worker and persistence layer."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    metadata: ResourceArtifactMetadata
    difficulty: str = Field(min_length=1, max_length=32)
    content_text: str = Field(min_length=1, max_length=500000)
    knowledge_points: List[str] = Field(min_length=1, max_length=50)
    artifact_data: Dict[str, Any] = Field(default_factory=dict)
    storage_type: Literal["text", "file"] = "text"
    mime_type: Optional[str] = None
    sanitization_warnings: List[str] = Field(default_factory=list, max_length=100)
    llm_metadata: Dict[str, Any] = Field(default_factory=dict)

    def to_learning_resource_fields(self) -> Dict[str, Any]:
        """Return the common fields used to materialize a LearningResource."""

        return {
            "resource_type": self.metadata.resource_type,
            "difficulty": self.difficulty,
            "storage_type": self.storage_type,
            "content_text": self.content_text,
            "mime_type": self.mime_type,
            "knowledge_points": list(self.knowledge_points),
        }


class AssessmentOption(StrictLLMOutput):
    option_id: str = Field(pattern=r"^[A-Z][A-Z0-9]{0,3}$")
    text: str = Field(min_length=1, max_length=400)


class AssessmentQuestion(StrictLLMOutput):
    question_id: str = Field(pattern=r"^q-[0-9]{2,3}$")
    level: Literal["基础", "进阶", "挑战"]
    question_type: Literal["single_choice", "multiple_choice", "true_false", "short_answer"]
    stem: str = Field(min_length=1, max_length=600)
    options: List[AssessmentOption] = Field(default_factory=list, max_length=4)
    answer: List[str] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=600)
    ability_node: str = Field(min_length=1, max_length=120)
    knowledge_points: List[str] = Field(min_length=1, max_length=5)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def validate_answer(self) -> "AssessmentQuestion":
        option_ids = [item.option_id for item in self.options]
        if len(option_ids) != len(set(option_ids)):
            raise ValueError("assessment option_id must be unique")
        choice_types = {"single_choice", "multiple_choice"}
        if self.question_type in choice_types:
            if len(option_ids) < 2 or not set(self.answer) <= set(option_ids):
                raise ValueError("choice answers must reference declared options")
            if self.question_type == "single_choice" and len(self.answer) != 1:
                raise ValueError("single choice question requires one answer")
        elif self.options:
            raise ValueError("non-choice questions cannot declare options")
        return self


class AssessmentLLMOutput(StrictLLMOutput):
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=600)
    difficulty: str = Field(min_length=1, max_length=32)
    questions: List[AssessmentQuestion] = Field(min_length=3, max_length=8)
    knowledge_points: List[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_levels_and_ids(self) -> "AssessmentLLMOutput":
        question_ids = [item.question_id for item in self.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("assessment question_id must be unique")
        if {item.level for item in self.questions} != {"基础", "进阶", "挑战"}:
            raise ValueError("assessment must cover 基础, 进阶 and 挑战 levels")
        return self


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
    action: str = Field(min_length=1, max_length=600)
    priority: int = Field(default=1, ge=1, le=100)


class ReviewLLMOutput(StrictLLMOutput):
    decision: Literal["approve", "revise", "reject", "human_review"]
    hallucination_score: float = Field(ge=0.0, le=1.0)
    issues: List[ReviewIssue] = Field(default_factory=list, max_length=3)
    difficulty_match: bool
    coverage_rate: float = Field(ge=0.0, le=1.0)
    suggestion: str = Field(min_length=1, max_length=500)
    revision_instructions: List[RevisionInstruction] = Field(default_factory=list, max_length=1)

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
