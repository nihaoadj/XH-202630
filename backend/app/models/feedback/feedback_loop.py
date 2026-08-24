"""Strict P0-07 contracts for durable post-learning feedback."""

from __future__ import annotations

import math
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from app.models.learners.mastery import LearningIntent, NextGenerationOptionsV1


FEEDBACK_SCHEMA_VERSION = "1.0"


def _is_json_safe(value: Any) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, list):
        return all(_is_json_safe(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _is_json_safe(item) for key, item in value.items())
    return False


class FeedbackAction(str, Enum):
    REMEDIATE = "remediate"
    PRACTICE = "practice"
    ADVANCE = "advance"
    HOLD = "hold"
    HUMAN_REVIEW = "human_review"


class PathNodeType(str, Enum):
    CORE = "core"
    REMEDIAL = "remedial"
    PRACTICE = "practice"
    CHALLENGE = "challenge"


class PathNodeStatus(str, Enum):
    LOCKED = "locked"
    AVAILABLE = "available"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class PathMutationType(str, Enum):
    INSERT_REMEDIAL = "insert_remedial"
    INSERT_PRACTICE = "insert_practice"
    ADVANCE = "advance"
    HOLD = "hold"


class FollowUpGenerationStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    QUEUED = "queued"
    FAILED = "failed"


class StrictFeedbackModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class KnowledgePointAttemptResult(StrictFeedbackModel):
    knowledge_point_id: str = Field(min_length=1, max_length=256)
    question_ids: list[str] = Field(min_length=1, max_length=500)
    correct_count: int = Field(ge=0)
    total_count: int = Field(gt=0)
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    duration_ms: int = Field(default=0, ge=0)
    hint_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_result(self) -> "KnowledgePointAttemptResult":
        if self.correct_count > self.total_count:
            raise ValueError("correct_count cannot exceed total_count")
        if len(self.question_ids) != len(set(self.question_ids)):
            raise ValueError("question_ids must be unique")
        computed = self.correct_count / self.total_count
        if self.score is not None and not math.isclose(self.score, computed, abs_tol=1e-9):
            raise ValueError("score does not match correct_count / total_count")
        self.score = computed
        return self


class LearningAttemptSubmit(StrictFeedbackModel):
    learner_id: str = Field(min_length=1, max_length=64)
    source_resource_id: str = Field(min_length=1, max_length=64)
    source_resource_version: int = Field(default=1, ge=1)
    source_run_id: str | None = Field(default=None, max_length=128)
    path_node_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=128)
    expected_profile_version: int = Field(ge=1)
    started_at: datetime | None = None
    submitted_at: datetime
    duration_ms: int = Field(default=0, ge=0)
    hint_count: int = Field(default=0, ge=0)
    overall_score: float | None = Field(default=None, ge=0.0, le=1.0)
    knowledge_point_results: list[KnowledgePointAttemptResult] = Field(min_length=1, max_length=500)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def validate_metadata(cls, value: dict[str, Any]) -> dict[str, Any]:
        allowed = {
            "source",
            "client_version",
            "session_id",
            "evaluation_source",
            "question_count",
            "question_trace",
            "point_trace",
            "learning_reflection",
            "llm_analysis",
            "question_results",
            "total_score",
            "max_score",
        }
        if set(value) - allowed:
            raise ValueError("metadata contains unsupported keys")
        if not _is_json_safe(value):
            raise ValueError("metadata values must be JSON-safe")
        return value

    @model_validator(mode="after")
    def validate_attempt(self) -> "LearningAttemptSubmit":
        point_ids = [item.knowledge_point_id for item in self.knowledge_point_results]
        if len(point_ids) != len(set(point_ids)):
            raise ValueError("knowledge_point_results must be unique by knowledge_point_id")
        total = sum(item.total_count for item in self.knowledge_point_results)
        correct = sum(item.correct_count for item in self.knowledge_point_results)
        computed = correct / total
        if self.overall_score is not None and not math.isclose(self.overall_score, computed, abs_tol=1e-9):
            raise ValueError("overall_score does not match point result totals")
        self.overall_score = computed
        if self.started_at and self.started_at > self.submitted_at:
            raise ValueError("started_at cannot be after submitted_at")
        return self


class LearningAttempt(StrictFeedbackModel):
    schema_version: Literal["1.0"] = FEEDBACK_SCHEMA_VERSION
    attempt_id: str = Field(min_length=1, max_length=128)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    learner_id: str
    source_resource_id: str
    source_resource_version: int = Field(ge=1)
    source_run_id: str | None = None
    path_node_id: str | None = None
    idempotency_key: str
    expected_profile_version: int = Field(ge=1)
    started_at: datetime | None = None
    submitted_at: datetime
    duration_ms: int = Field(ge=0)
    hint_count: int = Field(ge=0)
    overall_score: float = Field(ge=0.0, le=1.0)
    knowledge_point_results: list[KnowledgePointAttemptResult]
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class KnowledgeStateValue(StrictFeedbackModel):
    mastery: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["unassessed", "self_reported", "weak", "learning", "mastered"]
    self_report_prior: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: Literal["none", "low", "medium", "high"] = "none"
    objective_evidence_count: int = Field(default=0, ge=0)
    distinct_objective_source_count: int = Field(default=0, ge=0)
    attempt_count: int = Field(ge=0)
    last_evidence_type: str | None = None
    last_evidence_id: str | None = None
    last_attempt_id: str | None = None
    row_version: int = Field(ge=0)


class KnowledgeStateMutation(StrictFeedbackModel):
    knowledge_point_id: str
    before: KnowledgeStateValue | None = None
    after: KnowledgeStateValue
    source_attempt_id: str
    reason: str


class LearningPathNode(StrictFeedbackModel):
    node_id: str
    path_id: str
    knowledge_point_id: str
    node_type: PathNodeType
    sequence: int = Field(ge=1)
    status: PathNodeStatus
    prerequisite_ids: list[str] = Field(default_factory=list)
    parent_node_id: str | None = None
    source: Literal["planner", "feedback", "legacy"] = "feedback"
    difficulty: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class LearningPath(StrictFeedbackModel):
    path_id: str
    learner_id: str
    version: int = Field(ge=1)
    status: Literal["active", "completed", "archived"] = "active"
    nodes: list[LearningPathNode] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class PathMutation(StrictFeedbackModel):
    mutation_id: str
    learner_id: str
    path_id: str
    attempt_id: str
    decision_id: str
    mutation_type: PathMutationType
    target_node_id: str | None = None
    inserted_node_ids: list[str] = Field(default_factory=list)
    unlocked_node_ids: list[str] = Field(default_factory=list)
    completed_node_ids: list[str] = Field(default_factory=list)
    reason_codes: list[str] = Field(default_factory=list)
    path_version_before: int = Field(ge=1)
    path_version_after: int = Field(ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackDecision(StrictFeedbackModel):
    decision_id: str
    learner_id: str
    attempt_id: str
    action: FeedbackAction
    reason_codes: list[str] = Field(min_length=1)
    decision_reason: str = Field(min_length=1, max_length=2000)
    target_knowledge_point_ids: list[str] = Field(default_factory=list)
    recommended_tier: int | None = Field(default=None, ge=1, le=3)
    remediation_return_tier: int | None = Field(default=None, ge=1, le=3)
    tier_transition: str | None = Field(default=None, max_length=64)
    decision_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ProfileVersionRecord(StrictFeedbackModel):
    learner_id: str
    profile_version: int = Field(ge=1)
    source_attempt_id: str
    source_decision_id: str
    change_summary: dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FeedbackAnalysis(StrictFeedbackModel):
    """LLM interpretation of a scored attempt; it never changes scores directly."""

    summary: str = Field(min_length=1, max_length=1200)
    reflection_insight: str = Field(min_length=1, max_length=1000)
    profile_update_suggestions: list[str] = Field(default_factory=list, max_length=8)
    learner_suggestions: list[str] = Field(min_length=1, max_length=6)
    report_highlights: list[str] = Field(default_factory=list, max_length=6)
    analysis_status: Literal["llm", "fallback"] = "llm"


class FeedbackResourceOption(StrictFeedbackModel):
    option_id: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(min_length=1, max_length=400)
    resource_types: list[Literal["讲义", "实操指南", "分阶测试题", "复习清单", "案例分析"]] = Field(min_length=1, max_length=3)
    difficulty: Literal["初级", "中级", "高级"]
    target_knowledge_point_ids: list[str] = Field(default_factory=list, max_length=20)


class CorrectionPackageOptionV1(StrictFeedbackModel):
    """Feedback-only choice for a single, evidence-scoped remediation pack."""

    option_id: Literal["personalized-correction-package-v1"] = "personalized-correction-package-v1"
    resource_type: Literal["个性化纠错训练包"] = "个性化纠错训练包"
    title: str = "薄弱点强化包"
    eligible: bool
    disabled_reason_code: str | None = None
    selectable_targets: list[dict[str, Any]] = Field(default_factory=list, max_length=20)
    recommended_target_ids: list[str] = Field(default_factory=list, max_length=3)
    min_targets: Literal[1] = 1
    max_targets: Literal[3] = 3
    recommended_difficulty: Literal["初级", "中级", "高级"] = "中级"
    snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class FeedbackFollowupSelection(StrictFeedbackModel):
    learner_id: str = Field(min_length=1, max_length=64)
    attempt_id: str = Field(min_length=1, max_length=128)
    option_id: str = Field(min_length=1, max_length=64)
    # The recommendation is a starting point, not an automatic curriculum
    # decision.  Learners explicitly choose the artifacts they want next.
    resource_types: list[Literal["讲义", "实操指南", "分阶测试题", "复习清单", "案例分析"]] | None = Field(
        default=None, min_length=1, max_length=3,
    )
    difficulty: Literal["初级", "中级", "高级"] | None = None
    learning_intent: LearningIntent | None = None
    selected_skill_node_ids: list[str] = Field(default_factory=list, max_length=3)
    next_generation_snapshot_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("resource_types")
    @classmethod
    def validate_resource_types(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and len(value) != len(set(value)):
            raise ValueError("resource_types must be unique")
        return value

    @model_validator(mode="after")
    def validate_learning_intent_selection(self) -> "FeedbackFollowupSelection":
        intent_fields = (self.learning_intent, self.next_generation_snapshot_hash, self.selected_skill_node_ids)
        if any(item is not None and item != [] for item in intent_fields):
            if self.learning_intent is None or self.next_generation_snapshot_hash is None:
                raise ValueError("learning intent requires a snapshot hash")
            if not self.selected_skill_node_ids:
                raise ValueError("learning intent requires selected skill nodes")
        if len(self.selected_skill_node_ids) != len(set(self.selected_skill_node_ids)):
            raise ValueError("selected_skill_node_ids must be unique")
        return self


class FeedbackLoopResult(StrictFeedbackModel):
    attempt: LearningAttempt
    decision: FeedbackDecision
    profile_version: int = Field(ge=1)
    knowledge_state_updates: list[KnowledgeStateMutation]
    learning_path: LearningPath
    path_mutation: PathMutation
    feedback_status: Literal["applied"] = "applied"
    followup_generation_status: FollowUpGenerationStatus = FollowUpGenerationStatus.NOT_REQUESTED
    followup_run_id: str | None = None
    followup_job_id: str | None = None
    followup_error_code: str | None = None
    analysis: FeedbackAnalysis | None = None
    resource_options: list[FeedbackResourceOption] = Field(default_factory=list)
    correction_package_option: CorrectionPackageOptionV1 | None = None
    generation_options: NextGenerationOptionsV1 | None = None
    feedback_report: dict[str, Any] = Field(default_factory=dict)
    idempotent_replay: bool = False


class FeedbackContext(StrictFeedbackModel):
    learner_id: str
    profile_version: int = Field(ge=1)
    knowledge_states: dict[str, KnowledgeStateValue] = Field(default_factory=dict)
    recent_point_scores: dict[str, list[float]] = Field(default_factory=dict)
    learning_path: LearningPath | None = None
