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
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)
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
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)


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
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)
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
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)
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
        evidence_ids = set(self.evidence_ids)
        for node_id, node_evidence_ids in self.node_evidence_map.items():
            if not node_id.strip() or not node_evidence_ids:
                raise ValueError("node evidence mappings require a node and evidence")
            if len(node_evidence_ids) != len(set(node_evidence_ids)):
                raise ValueError("node evidence mappings must be unique")
            if any(not item.strip() for item in node_evidence_ids) or not set(node_evidence_ids) <= evidence_ids:
                raise ValueError("node evidence mappings must be a subset of spec evidence")
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
    node_evidence_map: Dict[str, List[str]] = Field(default_factory=dict)
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


class PracticeGuideStepV2(StrictLLMOutput):
    """One source-bound, learner-visible operation in a practice guide."""

    step_id: str = Field(pattern=r"^step-[1-8]$")
    title: str = Field(min_length=1, max_length=120)
    goal: str = Field(min_length=1, max_length=400)
    actions: List[str] = Field(min_length=1, max_length=6)
    verification: str = Field(min_length=1, max_length=500)
    common_mistakes: List[str] = Field(default_factory=list, max_length=3)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)

    @field_validator("actions", "common_mistakes", "evidence_ids")
    @classmethod
    def validate_nonblank_unique_values(cls, values: List[str]) -> List[str]:
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("practice step lists must be nonblank and unique")
        return values


class PracticeGuidePackageV2(StrictLLMOutput):
    """Canonical JSON contract rendered into the public Markdown guide."""

    schema_version: Literal["2.0"] = "2.0"
    title: str = Field(min_length=1, max_length=160)
    preparation: List[str] = Field(min_length=1, max_length=6)
    steps: List[PracticeGuideStepV2] = Field(min_length=1, max_length=8)
    completion_checklist: List[str] = Field(min_length=1, max_length=8)
    troubleshooting: List[str] = Field(default_factory=list, max_length=5)
    reflection: str = Field(min_length=1, max_length=600)

    @field_validator("preparation", "completion_checklist", "troubleshooting")
    @classmethod
    def validate_nonblank_rows(cls, values: List[str]) -> List[str]:
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("practice package lists must be nonblank and unique")
        return values

    @model_validator(mode="after")
    def validate_step_ids(self) -> "PracticeGuidePackageV2":
        step_ids = [item.step_id for item in self.steps]
        if step_ids != [f"step-{index}" for index in range(1, len(self.steps) + 1)]:
            raise ValueError("practice steps must use consecutive step IDs starting at step-1")
        return self


class PracticeGuidePreparationPhaseV3(StrictLLMOutput):
    phase_id: Literal["prepare"] = "prepare"
    goal: str = Field(min_length=1, max_length=400)
    items: List[str] = Field(min_length=1, max_length=6)
    evidence_ids: List[str] = Field(min_length=1, max_length=6)


class PracticeGuideCodeBlockV3(StrictLLMOutput):
    language: str = Field(min_length=1, max_length=40)
    code: str = Field(min_length=1, max_length=8000)
    purpose: str = Field(min_length=1, max_length=400)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)

    @field_validator("evidence_ids")
    @classmethod
    def validate_evidence_ids(cls, values: List[str]) -> List[str]:
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("practice code evidence IDs must be nonblank and unique")
        return values


class PracticeGuideStepV3(StrictLLMOutput):
    step_id: str = Field(pattern=r"^step-[1-8]$")
    title: str = Field(min_length=1, max_length=120)
    # Exactly three learner-content fields: instruction, code, and verification.
    instruction_text: str = Field(min_length=1, max_length=1200)
    code_blocks: List[PracticeGuideCodeBlockV3] = Field(default_factory=list, max_length=3)
    verification: str = Field(min_length=1, max_length=500)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)

    @field_validator("evidence_ids")
    @classmethod
    def validate_nonblank_unique_values(cls, values: List[str]) -> List[str]:
        if any(not value.strip() for value in values) or len(values) != len(set(values)):
            raise ValueError("practice step lists must be nonblank and unique")
        return values


class PracticeGuideExecutionPhaseV3(StrictLLMOutput):
    phase_id: Literal["practice"] = "practice"
    goal: str = Field(min_length=1, max_length=400)
    steps: List[PracticeGuideStepV3] = Field(min_length=1, max_length=8)


class PracticeGuideVerificationPhaseV3(StrictLLMOutput):
    phase_id: Literal["verify"] = "verify"
    goal: str = Field(min_length=1, max_length=400)
    checklist: List[str] = Field(min_length=1, max_length=8)
    evidence_ids: List[str] = Field(min_length=1, max_length=6)


class PracticeGuideReflectionPhaseV3(StrictLLMOutput):
    phase_id: Literal["reflect"] = "reflect"
    goal: str = Field(min_length=1, max_length=400)
    summary: str = Field(min_length=1, max_length=600)
    evidence_ids: List[str] = Field(min_length=1, max_length=6)


class PracticeGuidePackageV3(StrictLLMOutput):
    """Fixed four-phase source contract for guides and courseware."""

    schema_version: Literal["3.0"] = "3.0"
    title: str = Field(min_length=1, max_length=160)
    preparation: PracticeGuidePreparationPhaseV3
    practice: PracticeGuideExecutionPhaseV3
    verification: PracticeGuideVerificationPhaseV3
    reflection: PracticeGuideReflectionPhaseV3

    @model_validator(mode="after")
    def validate_structure(self) -> "PracticeGuidePackageV3":
        step_ids = [item.step_id for item in self.practice.steps]
        if step_ids != [f"step-{index}" for index in range(1, len(self.practice.steps) + 1)]:
            raise ValueError("practice steps must use consecutive step IDs starting at step-1")
        for values in (
            self.preparation.items, self.preparation.evidence_ids,
            self.verification.checklist, self.verification.evidence_ids,
            self.reflection.evidence_ids,
        ):
            if any(not value.strip() for value in values) or len(values) != len(set(values)):
                raise ValueError("practice phase lists must be nonblank and unique")
        content = "\n".join([
            self.preparation.goal, *self.preparation.items,
            self.practice.goal,
            *(value for step in self.practice.steps for value in (
                step.title, step.instruction_text, step.verification,
                *(item.purpose for item in step.code_blocks), *(item.code for item in step.code_blocks),
            )),
            self.verification.goal, *self.verification.checklist,
            self.reflection.goal, self.reflection.summary,
        ])
        forbidden_resource_labels = ("分阶测试题", "复习清单", "案例分析", "讲义")
        if any(label in content for label in forbidden_resource_labels):
            raise ValueError("practice guide must not embed another learning-resource type")
        return self


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


# V2 is deliberately node-scoped.  The model never receives a whole batch,
# which keeps a single malformed node from invalidating an otherwise usable
# response and lets the workflow checkpoint completed node blocks.
class AssessmentChoiceQuestionV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^(single|multiple)-[12]$")
    question_type: Literal["single_choice", "multiple_choice"]
    stem: str = Field(min_length=1, max_length=600)
    options: List[AssessmentOption] = Field(min_length=4, max_length=4)
    answer_option_ids: List[str] = Field(min_length=1, max_length=3)
    knowledge_point_tags: List[str] = Field(min_length=1, max_length=3)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)
    # Assigned deterministically by the server after all node calls succeed.
    question_id: str | None = Field(default=None, pattern=r"^q-[0-9]{3}$")
    max_score: float | None = Field(default=None, gt=0, le=100)
    # The server, not the model, fixes the stage from question type.
    difficulty_stage: Literal["基础", "进阶", "挑战"] | None = None

    @model_validator(mode="after")
    def validate_choice(self) -> "AssessmentChoiceQuestionV2":
        ids = [item.option_id for item in self.options]
        if ids != ["A", "B", "C", "D"]:
            raise ValueError("assessment choices must use exactly A/B/C/D")
        if not set(self.answer_option_ids) <= set(ids):
            raise ValueError("choice answers must reference declared options")
        if self.question_type == "single_choice" and len(self.answer_option_ids) != 1:
            raise ValueError("single choice requires exactly one answer")
        if self.question_type == "multiple_choice" and not 2 <= len(self.answer_option_ids) < 4:
            raise ValueError("multiple choice requires two or three answers")
        return self


class AssessmentRubricItemV2(StrictLLMOutput):
    criterion: str = Field(min_length=1, max_length=300)
    points: int = Field(ge=1, le=10)


class AssessmentShortAnswerQuestionV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^short-[12]$")
    question_type: Literal["short_answer"] = "short_answer"
    stem: str = Field(min_length=1, max_length=600)
    reference_answer: str = Field(min_length=1, max_length=1200)
    rubric: List[AssessmentRubricItemV2] = Field(min_length=2, max_length=6)
    knowledge_point_tags: List[str] = Field(min_length=1, max_length=3)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)
    # Assigned deterministically by the server after all node calls succeed.
    question_id: str | None = Field(default=None, pattern=r"^q-[0-9]{3}$")
    max_score: float | None = Field(default=None, gt=0, le=100)
    # The server, not the model, fixes the stage from question type.
    difficulty_stage: Literal["基础", "进阶", "挑战"] | None = None


class AssessmentNodeBlockV2(StrictLLMOutput):
    schema_version: Literal["2.0"] = "2.0"
    skill_node_id: str = Field(min_length=1, max_length=128)
    skill_node_name: str = Field(min_length=1, max_length=160)
    single_choice_questions: List[AssessmentChoiceQuestionV2] = Field(min_length=2, max_length=2)
    multiple_choice_questions: List[AssessmentChoiceQuestionV2] = Field(min_length=1, max_length=1)
    short_answer_questions: List[AssessmentShortAnswerQuestionV2] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def validate_fixed_quota(self) -> "AssessmentNodeBlockV2":
        if any(item.question_type != "single_choice" for item in self.single_choice_questions):
            raise ValueError("single_choice_questions must contain only single_choice")
        if self.multiple_choice_questions[0].question_type != "multiple_choice":
            raise ValueError("multiple_choice_questions must contain one multiple_choice")
        local_ids = [item.local_id for item in self.single_choice_questions + self.multiple_choice_questions + self.short_answer_questions]
        if len(local_ids) != len(set(local_ids)):
            raise ValueError("node-local question IDs must be unique")
        return self


class AssessmentPackageV2(StrictLLMOutput):
    schema_version: Literal["2.0"] = "2.0"
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=600)
    node_blocks: List[AssessmentNodeBlockV2] = Field(min_length=1, max_length=50)


class AssessmentShortAnswerGradeV1(StrictLLMOutput):
    score: float = Field(ge=0.0)
    feedback: str = Field(min_length=1, max_length=600)


class AssessmentScopeFindingV1(StrictLLMOutput):
    question_id: str = Field(pattern=r"^q-[0-9]{3}$")
    decision: Literal["in_scope", "out_of_scope", "insufficient_evidence"]
    reason: str = Field(min_length=1, max_length=120)
    # One directly supporting excerpt is sufficient for an auditable finding;
    # bounding this prevents a scope audit from expanding into a long essay.
    supported_evidence_ids: List[str] = Field(default_factory=list, max_length=1)


class AssessmentScopeReviewV1(StrictLLMOutput):
    findings: List[AssessmentScopeFindingV1] = Field(min_length=1, max_length=250)


class ReviewRecallQuestionV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^recall-[1-4]$")
    prompt: str = Field(min_length=1, max_length=800)
    reference_answer: str = Field(min_length=1, max_length=1600)
    explanation: str = Field(min_length=1, max_length=1200)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)
    pass_criteria: str = Field(min_length=1, max_length=500)
    question_id: str | None = Field(default=None, pattern=r"^q-[0-9]{3}$")


class ReviewDistinctionQuestionV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^distinction-[1-4]$")
    statement: str = Field(min_length=1, max_length=800)
    truth_value: bool
    correction: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=1200)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)
    pass_criteria: str = Field(min_length=1, max_length=500)
    question_id: str | None = Field(default=None, pattern=r"^q-[0-9]{3}$")


class ReviewExampleRecognitionQuestionV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^example-[1-2]$", default="example-1")
    candidate_a: str = Field(min_length=1, max_length=600)
    candidate_b: str = Field(min_length=1, max_length=600)
    positive_candidate: Literal["A", "B"]
    decisive_boundary: str = Field(min_length=1, max_length=800)
    explanation: str = Field(min_length=1, max_length=1200)
    evidence_ids: List[str] = Field(min_length=1, max_length=3)
    pass_criteria: str = Field(min_length=1, max_length=500)
    question_id: str | None = Field(default=None, pattern=r"^q-[0-9]{3}$")


class ReviewOmittedSlotV2(StrictLLMOutput):
    local_id: str = Field(pattern=r"^(recall|distinction)-[1-4]$|^example-[1-2]$")
    reason: Literal["INSUFFICIENT_DISTINCT_EVIDENCE", "NO_EXPLICIT_CONCEPT_BOUNDARY"]


class ReviewPracticeNodeBlockV2(StrictLLMOutput):
    schema_version: Literal["2.0"] = "2.0"
    skill_node_id: str = Field(min_length=1, max_length=128)
    skill_node_name: str = Field(min_length=1, max_length=160)
    recall_questions: List[ReviewRecallQuestionV2] = Field(min_length=1, max_length=4)
    distinction_questions: List[ReviewDistinctionQuestionV2] = Field(min_length=1, max_length=4)
    # Keep the singular field for backward compatibility with persisted V2
    # packages; new generation uses the list to support the expanded quota.
    example_recognition: ReviewExampleRecognitionQuestionV2 | None = None
    example_recognition_questions: List[ReviewExampleRecognitionQuestionV2] = Field(default_factory=list, max_length=2)
    omitted_slots: List[ReviewOmittedSlotV2] = Field(default_factory=list, max_length=10)
    knowledge_summary: str = Field(min_length=100, max_length=1400)
    summary_evidence_ids: List[str] = Field(min_length=1, max_length=3)
    evidence_ids: List[str] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_slots(self) -> "ReviewPracticeNodeBlockV2":
        actual = [item.local_id for item in self.recall_questions + self.distinction_questions]
        examples = list(self.example_recognition_questions)
        if self.example_recognition:
            examples.append(self.example_recognition)
        actual.extend(item.local_id for item in examples)
        omitted = [item.local_id for item in self.omitted_slots]
        if len(actual) != len(set(actual)) or len(omitted) != len(set(omitted)) or set(actual) & set(omitted):
            raise ValueError("review question and omitted slot IDs must be unique")
        expected = {
            *(f"recall-{index}" for index in range(1, 5)),
            *(f"distinction-{index}" for index in range(1, 5)),
            *(f"example-{index}" for index in range(1, 3)),
        }
        if set(actual) | set(omitted) != expected:
            raise ValueError("review node must account for every fixed slot")
        if len(self.distinction_questions) >= 2 and len({item.truth_value for item in self.distinction_questions}) != 2:
            raise ValueError("multiple distinction questions require both true and false statements")
        if not set(self.summary_evidence_ids) <= set(self.evidence_ids):
            raise ValueError("summary evidence must be included in node evidence")
        return self


class ReviewPracticePackageV2(StrictLLMOutput):
    schema_version: Literal["2.0"] = "2.0"
    title: str = Field(min_length=1, max_length=120)
    instructions: str = Field(min_length=1, max_length=1000)
    node_blocks: List[ReviewPracticeNodeBlockV2] = Field(min_length=1, max_length=3)
    payload_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


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
