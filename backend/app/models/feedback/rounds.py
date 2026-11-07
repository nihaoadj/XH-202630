"""Versioned contracts for learning rounds; authority stays on the server."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.feedback.feedback_loop import FeedbackAction
from app.models.learners.mastery import LearningIntent, NextGenerationOptionsV1, NextGenerationCandidateV1
from app.models.learning_documents.schemas import GenerateCreateRequest, ResourceEvaluationQuestion
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES, canonical_resource_type


class RoundModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class GenerationCapabilitiesV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    protocol_version: Literal["learning-round/v1"] = "learning-round/v1"
    round_creation_enabled: bool
    single_target_required: Literal[True] = True
    round_query_available: bool
    round_recovery_available: bool


class RoundIdentityMemberV1(RoundModel):
    member_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]


class RoundIdentityV1(RoundModel):
    """Validate roles without inventing one for imported legacy members."""

    protocol_version: Literal["learning-round/v1", "legacy-correction/v1"]
    members: list[RoundIdentityMemberV1] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_members(self) -> RoundIdentityV1:
        if len({member.member_id for member in self.members}) != len(self.members):
            raise ValueError("member IDs must be unique")
        if len({member.node_id for member in self.members}) != len(self.members):
            raise ValueError("node IDs must be unique")
        roles = [member.role for member in self.members]
        if self.protocol_version == "learning-round/v1":
            if roles.count("primary") != 1 or roles.count("review") > 1 or "legacy" in roles:
                raise ValueError("normal round requires one primary and at most one review")
        elif any(role != "legacy" for role in roles):
            raise ValueError("legacy round members must not be assigned a primary or review role")
        return self


class RoundJobBindingV1(RoundModel):
    """Server-side binding snapshot; accepting these fields does not grant authority."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)

    protocol_version: Literal["learning-round/v1", "legacy-correction/v1"]
    round_id: str = Field(min_length=1, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)
    stage_node_id: str = Field(min_length=1, max_length=128)
    batch_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]
    stage_kind: Literal["initial", "correction"]

    @model_validator(mode="after")
    def validate_protocol(self) -> RoundJobBindingV1:
        if (self.protocol_version == "legacy-correction/v1") != (self.role == "legacy"):
            raise ValueError("binding role must match its protocol")
        if self.protocol_version == "legacy-correction/v1" and self.stage_kind != "correction":
            raise ValueError("legacy initial imports have no production binding")
        return self


class GenerateRoundCreateRequestV1(GenerateCreateRequest):
    """A round may split multiple selected Claim resources into separate jobs."""

    model_config = ConfigDict(extra="forbid")
    schema_version: Literal["1.0"] = "1.0"
    selection_key: str = Field(min_length=8, max_length=128)

    @field_validator("constraints")
    @classmethod
    def validate_public_constraints(cls, value: dict[str, Any]) -> dict[str, Any]:
        if set(value) - {"supplemental_requirements"}:
            raise ValueError("constraints contain server-controlled fields")
        return value

    @field_validator("resource_types")
    @classmethod
    def validate_general_resource_types(cls, values: list[str]) -> list[str]:
        if any(value not in GENERAL_GENERATION_RESOURCE_TYPES for value in values):
            raise ValueError("normal round accepts only general resource types")
        return values

    @model_validator(mode="after")
    def require_resource_review_for_claim_audit(self) -> GenerateRoundCreateRequestV1:
        if self.include_claim_check and not self.include_review:
            raise ValueError("include_claim_check requires include_review=true")
        return self


class RoundNextSelectionV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    source_attempt_id: str = Field(min_length=1, max_length=128)
    primary_node_id: str = Field(min_length=1, max_length=128)
    primary_learning_intent: LearningIntent
    primary_resource_types: list[str] = Field(min_length=1, max_length=5)
    review_node_id: str | None = Field(default=None, min_length=1, max_length=128)
    include_claim_check: bool = False
    selection_key: str = Field(min_length=8, max_length=128)

    @field_validator("primary_resource_types")
    @classmethod
    def validate_resource_types(cls, values: list[str]) -> list[str]:
        normalized = [canonical_resource_type(value) for value in values]
        if any(value not in GENERAL_GENERATION_RESOURCE_TYPES for value in normalized):
            raise ValueError("primary resource type is not a general resource")
        return normalized

    @model_validator(mode="after")
    def validate_selection(self) -> RoundNextSelectionV1:
        if self.review_node_id == self.primary_node_id:
            raise ValueError("primary and review must be different nodes")
        if len(set(self.primary_resource_types)) != len(self.primary_resource_types):
            raise ValueError("resource types must be unique")
        return self


class RoundCorrectionTargetV1(RoundModel):
    node_id: str = Field(min_length=1, max_length=128)
    source_attempt_id: str = Field(min_length=1, max_length=128)


class RoundCorrectionSelectionV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    targets: list[RoundCorrectionTargetV1] = Field(min_length=1, max_length=2)
    selection_key: str = Field(min_length=8, max_length=128)
    include_claim_check: bool = False

    @model_validator(mode="after")
    def validate_targets(self) -> RoundCorrectionSelectionV1:
        if len({target.node_id for target in self.targets}) != len(self.targets):
            raise ValueError("correction targets must have distinct nodes")
        return self


class RoundAnswerV1(RoundModel):
    question_id: str = Field(min_length=1, max_length=128)
    answer: Any

    @field_validator("answer")
    @classmethod
    def require_answer(cls, value: Any) -> Any:
        if value is None or (isinstance(value, str) and not value.strip()) or value == []:
            raise ValueError("answer must not be empty")
        return value


class RoundLearningReflectionV1(RoundModel):
    completed: bool | None = None
    time_spent_seconds: int | None = Field(default=None, ge=0)
    self_rating: int | None = Field(default=None, ge=1, le=5)
    difficulty_feeling: str | None = Field(default=None, max_length=256)
    helpful_part: str | None = Field(default=None, max_length=2000)
    confusing_part: str | None = Field(default=None, max_length=2000)
    comment: str | None = Field(default=None, max_length=2000)


class RoundAttemptSubmitV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    session_id: str = Field(min_length=1, max_length=128)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_profile_version: int = Field(ge=1)
    submitted_at: datetime
    duration_ms: int = Field(default=0, ge=0)
    answers: list[RoundAnswerV1] = Field(min_length=1, max_length=500)
    learning_reflection: RoundLearningReflectionV1 | None = None

    @model_validator(mode="after")
    def validate_submission(self) -> RoundAttemptSubmitV1:
        if self.submitted_at.utcoffset() is None:
            raise ValueError("submitted_at must include a timezone")
        self.submitted_at = self.submitted_at.astimezone(timezone.utc)
        ids = [answer.question_id for answer in self.answers]
        if len(ids) != len(set(ids)):
            raise ValueError("question IDs must be unique")
        return self


class RoundMemberJobsV1(RoundModel):
    member_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]
    node_id: str = Field(min_length=1, max_length=128)
    stage_node_id: str = Field(min_length=1, max_length=128)
    batch_id: str | None = Field(default=None, max_length=128)
    job_ids: list[str] = Field(default_factory=list)
    resource_types: list[str]
    difficulty: str | None = None
    resource_ids: list[str] = Field(default_factory=list)
    state: Literal["producing", "awaiting_assessment", "completed", "failed"]
    failed_job_count: int = Field(default=0, ge=0)


class RoundCreationResponseV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    round_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)
    primary_node_id: str | None
    members: list[RoundMemberJobsV1] = Field(min_length=1, max_length=2)
    state: Literal["producing", "awaiting_assessment", "completed"]
    primary_default_run_id: str | None = None

    @model_validator(mode="after")
    def validate_member_mapping(self) -> RoundCreationResponseV1:
        ids = [member.member_id for member in self.members]
        nodes = [member.node_id for member in self.members]
        roles = [member.role for member in self.members]
        if len(ids) != len(set(ids)) or len(nodes) != len(set(nodes)):
            raise ValueError("member and node IDs must be unique")
        if self.primary_node_id is None:
            if any(role != "legacy" for role in roles):
                raise ValueError("legacy creation has no primary or review role")
        elif "legacy" in roles or roles.count("primary") > 1 or roles.count("review") > 1:
            raise ValueError("normal creation has invalid member roles")
        primary = next((member for member in self.members if member.role == "primary"), None)
        if primary and primary.node_id != self.primary_node_id:
            raise ValueError("primary node must match the primary member")
        if (self.primary_default_run_id is not None and primary is not None
                and self.primary_default_run_id not in primary.job_ids):
            raise ValueError("default run must belong to the primary member")
        if self.primary_node_id is None and self.primary_default_run_id is not None:
            raise ValueError("legacy creation has no primary default run")
        return self


class RoundEvaluationGroupV1(RoundModel):
    member_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]
    questions: list[ResourceEvaluationQuestion] = Field(min_length=1)


class RoundEvaluationSessionV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    session_id: str = Field(min_length=1, max_length=128)
    round_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    groups: list[RoundEvaluationGroupV1] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_groups(self) -> RoundEvaluationSessionV1:
        members = [group.member_id for group in self.groups]
        nodes = [group.node_id for group in self.groups]
        roles = [group.role for group in self.groups]
        question_ids = [question.question_id for group in self.groups for question in group.questions]
        if (len(members) != len(set(members)) or len(nodes) != len(set(nodes))
                or len(question_ids) != len(set(question_ids))):
            raise ValueError("session member and question IDs must be unique")
        if roles.count("primary") > 1 or roles.count("review") > 1 or ("legacy" in roles and len(set(roles)) != 1):
            raise ValueError("session roles are inconsistent")
        return self

    def require_members(self, expected_member_ids: set[str]) -> None:
        """Compare groups with server-loaded stage membership, never client input."""
        if {group.member_id for group in self.groups} != expected_member_ids:
            raise ValueError("session does not contain exactly the stage members")


class RoundAttemptProcessingV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    state: Literal["grading"] = "grading"
    session_id: str = Field(min_length=1, max_length=128)
    retry_after_seconds: Literal[2] = 2


class RoundEvaluationRequestV1(RoundModel):
    learner_id: str = Field(min_length=1, max_length=64)


class RoundStageSummaryV1(RoundModel):
    stage_id: str = Field(min_length=1, max_length=128)
    kind: Literal["initial", "correction"]
    ordinal: int = Field(ge=0)
    state: Literal["producing", "awaiting_assessment", "completed"]
    members: list[RoundMemberJobsV1] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_ordinal(self) -> RoundStageSummaryV1:
        if (self.kind == "initial") != (self.ordinal == 0):
            raise ValueError("only an initial stage has ordinal zero")
        return self


class RoundMemberSummaryV1(RoundIdentityMemberV1):
    node_name: str = Field(min_length=1, max_length=256)
    tier: int | None = Field(default=None, ge=1, le=3)
    state: Literal["producing", "awaiting_assessment", "completed", "failed"]
    failed_job_count: int = Field(default=0, ge=0)
    resource_ids: list[str] = Field(default_factory=list)
    remediation_status: Literal["remediate", "practice", "resolved"] | None = None


class LearningRoundSummaryV1(RoundModel):
    round_id: str = Field(min_length=1, max_length=128)
    protocol_version: Literal["learning-round/v1", "legacy-correction/v1"]
    created_at: datetime
    members: list[RoundMemberSummaryV1] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_identity(self) -> LearningRoundSummaryV1:
        RoundIdentityV1(protocol_version=self.protocol_version, members=self.members)
        return self


class LearningRoundListV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    offset: int = Field(ge=0)
    limit: int = Field(ge=1)
    total: int = Field(ge=0)
    items: list[LearningRoundSummaryV1]


class LearningRoundDetailV1(LearningRoundSummaryV1):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    stages: list[RoundStageSummaryV1]
    available_actions: list[Literal["append_primary", "evaluate", "correct", "next", "retry"]]


class RoundNodeFeedbackV1(RoundModel):
    member_id: str = Field(min_length=1, max_length=128)
    node_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]
    score: float = Field(ge=0, le=1)
    action: FeedbackAction
    reason: str
    correction_eligible: bool
    remediation_status: Literal["remediate", "practice", "resolved"] | None = None
    source_attempt_id: str | None = None


class RoundFeedbackResultV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    round_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)
    session_id: str = Field(min_length=1, max_length=128)
    attempt_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    primary_path_action: FeedbackAction
    nodes: list[RoundNodeFeedbackV1] = Field(min_length=1, max_length=2)

    @model_validator(mode="after")
    def validate_primary_path(self) -> RoundFeedbackResultV1:
        if not any(node.role == "primary" for node in self.nodes) and self.primary_path_action != FeedbackAction.HOLD:
            raise ValueError("feedback without a primary must hold the primary path")
        return self


class RoundResultNotSubmittedV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    state: Literal["not_submitted"] = "not_submitted"
    round_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)


class RoundCandidatesV1(RoundModel):
    schema_version: Literal["1.0"] = "1.0"
    generation_options: NextGenerationOptionsV1
    eligible_review_nodes: list[NextGenerationCandidateV1]
    correction_targets: list[RoundCorrectionTargetV1]
    profile_version: int = Field(ge=1)
