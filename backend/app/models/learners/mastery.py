"""Versioned contracts for the canonical learner ability projection."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictMasteryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AbilityEvidenceSource(str, Enum):
    ONBOARDING_SELF_REPORT = "onboarding_self_report"
    COURSEWARE_SELF_REPORT = "courseware_self_report"
    DIAGNOSIS = "diagnosis"
    LEARNING_ATTEMPT = "learning_attempt"
    LEGACY_IMPORT = "legacy_import"


class AbilityStatus(str, Enum):
    UNASSESSED = "unassessed"
    SELF_REPORTED = "self_reported"
    WEAK = "weak"
    LEARNING = "learning"
    MASTERED = "mastered"


class LearningIntent(str, Enum):
    """The learner's explicit objective for the next resource batch."""

    REINFORCE_WEAKNESS = "reinforce_weakness"
    LEARN_NEW_KNOWLEDGE = "learn_new_knowledge"
    LEARN_NEW_AND_REINFORCE = "learn_new_and_reinforce"


class CurriculumProgressStatus(str, Enum):
    """Durable progress through a node's learning lifecycle.

    This is intentionally distinct from ``AbilityStatus``: publication tracks
    learning exposure while ability evidence tracks demonstrated mastery.
    """

    UNPLANNED = "unplanned"
    SCHEDULED = "scheduled"
    EXPOSED = "exposed"
    VERIFICATION_PENDING = "verification_pending"
    COMPLETED = "completed"
    REINFORCEMENT_DUE = "reinforcement_due"


class AbilityConfidence(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class AbilityEvidenceV1(StrictMasteryModel):
    schema_version: Literal["1.0"] = "1.0"
    evidence_id: str = Field(min_length=1, max_length=128)
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    skill_node_id: str = Field(min_length=1, max_length=128)
    source_type: AbilityEvidenceSource
    source_id: str = Field(min_length=1, max_length=128)
    source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    observed_score: float | None = Field(default=None, ge=0.0, le=1.0)
    verified: bool
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AbilityStateEventV1(AbilityEvidenceV1):
    before_state: "AbilityMasteryStateV2 | None" = None
    after_state: "AbilityMasteryStateV2"


class AbilityMasteryStateV2(StrictMasteryModel):
    schema_version: Literal["2.0"] = "2.0"
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    skill_node_id: str = Field(min_length=1, max_length=128)
    mastery_score: float | None = Field(default=None, ge=0.0, le=1.0)
    self_report_prior: float | None = Field(default=None, ge=0.0, le=1.0)
    status: AbilityStatus = AbilityStatus.UNASSESSED
    confidence: AbilityConfidence = AbilityConfidence.NONE
    objective_evidence_count: int = Field(default=0, ge=0)
    distinct_objective_source_count: int = Field(default=0, ge=0)
    attempt_count: int = Field(default=0, ge=0)
    last_evidence_type: AbilityEvidenceSource | None = None
    last_evidence_id: str | None = Field(default=None, max_length=128)
    row_version: int = Field(default=1, ge=1)
    last_updated: datetime | None = None


class AbilityNodeProjectionV1(StrictMasteryModel):
    skill_node_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    description: str | None = Field(default=None, max_length=4000)
    level: str | None = Field(default=None, max_length=64)
    tier: int = Field(default=1, ge=1, le=3)
    tier_label: str = Field(default="零基础", max_length=64)
    prerequisites: list[str] = Field(default_factory=list, max_length=128)
    children: list[str] = Field(default_factory=list, max_length=128)
    mastery: AbilityMasteryStateV2
    trend_delta: float | None = Field(default=None, ge=-1.0, le=1.0)
    priority: int | None = Field(default=None, ge=1)


class CurriculumNodeProgressV1(StrictMasteryModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    skill_node_id: str = Field(min_length=1, max_length=128)
    progress_status: CurriculumProgressStatus = CurriculumProgressStatus.UNPLANNED
    wait_rounds: int = Field(default=0, ge=0, le=5)
    scheduled_run_id: str | None = Field(default=None, max_length=128)
    published_resource_count: int = Field(default=0, ge=0)
    verified_attempt_count: int = Field(default=0, ge=0)
    placement_exempt: bool = False
    placement_evidence_id: str | None = Field(default=None, max_length=128)
    last_scheduled_at: datetime | None = None
    last_published_at: datetime | None = None
    last_verified_at: datetime | None = None
    row_version: int = Field(default=1, ge=1)
    updated_at: datetime | None = None


class CurriculumProgressSummaryV1(StrictMasteryModel):
    total_count: int = Field(ge=0)
    unplanned_count: int = Field(ge=0)
    scheduled_count: int = Field(ge=0)
    exposed_count: int = Field(ge=0)
    verification_pending_count: int = Field(ge=0)
    completed_count: int = Field(ge=0)
    reinforcement_due_count: int = Field(ge=0)


class LearnerTierProgressV1(StrictMasteryModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    placement_tier: int = Field(ge=1, le=3)
    active_tier: int = Field(ge=1, le=3)
    highest_unlocked_tier: int = Field(ge=1, le=3)
    remediation_return_tier: int | None = Field(default=None, ge=1, le=3)
    profile_version: int = Field(ge=1)
    row_version: int = Field(default=1, ge=1)
    updated_at: datetime | None = None


class WeaknessPriorityV1(StrictMasteryModel):
    skill_node_id: str = Field(min_length=1, max_length=128)
    rank: int = Field(ge=1)
    priority_group: Literal[
        "confirmed_weak",
        "regressing_learning",
        "ready_uncovered",
        "low_self_report",
        "blocked_uncovered",
        "maintain_mastery",
    ]
    reason_codes: list[str] = Field(min_length=1, max_length=16)
    mastery_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: AbilityConfidence
    downstream_count: int = Field(default=0, ge=0)
    coverage_status: Literal["uncovered", "covered"] = "uncovered"
    published_resource_count: int = Field(default=0, ge=0)


class LearnerFocusSkippedV1(StrictMasteryModel):
    skill_node_id: str = Field(min_length=1, max_length=128)
    reason_code: str = Field(min_length=1, max_length=64)


class LearnerFocusSnapshotV1(StrictMasteryModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    mastery_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    focus_mode: Literal["auto", "off", "explicit"]
    ranked_priorities: list[WeaknessPriorityV1] = Field(default_factory=list, max_length=256)
    adopted_node_ids: list[str] = Field(default_factory=list, max_length=256)
    skipped: list[LearnerFocusSkippedV1] = Field(default_factory=list, max_length=256)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class NextGenerationCandidateV1(StrictMasteryModel):
    skill_node_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=256)
    priority_group: Literal["learned_not_mastered", "unlearned"]
    rank: int = Field(ge=1)
    reason_codes: list[str] = Field(min_length=1, max_length=8)
    mastery_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: AbilityConfidence
    prerequisite_ids: list[str] = Field(default_factory=list, max_length=32)
    blocked_by_node_ids: list[str] = Field(default_factory=list, max_length=32)
    tier: int = Field(ge=1, le=3)
    tier_label: str = Field(min_length=1, max_length=64)
    eligibility_status: Literal["available", "blocked", "placement_exempt"] = "available"


class NextGenerationOptionsV1(StrictMasteryModel):
    """Server calculated, mutually exclusive candidate sets for the next step."""

    schema_version: Literal["1.0"] = "1.0"
    learner_id: str = Field(min_length=1, max_length=64)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    profile_version: int = Field(ge=1)
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    reinforce_weakness: list[NextGenerationCandidateV1] = Field(default_factory=list)
    learn_new_knowledge: list[NextGenerationCandidateV1] = Field(default_factory=list)
    recommended_node_ids: list[str] = Field(default_factory=list, max_length=2)
    curriculum_progress: CurriculumProgressSummaryV1 | None = None
    tier_progress: LearnerTierProgressV1 | None = None
    tier_completion: bool = False
    recommendation_type: Literal["remedial", "practice", "current_tier", "advance", "complete"] = "current_tier"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class AbilityNodeSummaryV1(StrictMasteryModel):
    total_count: int = Field(ge=0)
    mastered_count: int = Field(ge=0)
    learning_count: int = Field(ge=0)
    weak_count: int = Field(ge=0)
    self_reported_count: int = Field(ge=0)
    unassessed_count: int = Field(ge=0)
    medium_or_high_confidence_count: int = Field(ge=0)


class AbilityNodesResponseV1(StrictMasteryModel):
    schema_version: Literal["1.0"] = "1.0"
    learner_id: str
    knowledge_base_id: str | None
    as_of_profile_version: int = Field(ge=1)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    summary: AbilityNodeSummaryV1
    nodes: list[AbilityNodeProjectionV1] = Field(default_factory=list)
    edges: list[dict[str, str]] = Field(default_factory=list)
    weakness_priorities: list[WeaknessPriorityV1] = Field(default_factory=list)
    curriculum_progress: CurriculumProgressSummaryV1 | None = None
    curriculum_nodes: list[CurriculumNodeProgressV1] = Field(default_factory=list)
    data_warnings: list[str] = Field(default_factory=list)


__all__ = [
    "AbilityConfidence",
    "CurriculumNodeProgressV1",
    "CurriculumProgressStatus",
    "CurriculumProgressSummaryV1",
    "LearnerTierProgressV1",
    "AbilityEvidenceSource",
    "AbilityEvidenceV1",
    "AbilityStateEventV1",
    "AbilityMasteryStateV2",
    "AbilityNodeProjectionV1",
    "AbilityNodesResponseV1",
    "AbilityNodeSummaryV1",
    "AbilityStatus",
    "LearningIntent",
    "NextGenerationCandidateV1",
    "NextGenerationOptionsV1",
    "LearnerFocusSkippedV1",
    "LearnerFocusSnapshotV1",
    "WeaknessPriorityV1",
]
