"""Public DTOs for learning reports and evaluation summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.learning_documents.schemas import (
    AgentTrace,
    FeedbackRecord,
    LearningPathItem,
    LearningResource,
)
from app.models.learners.mastery import AbilityNodeProjectionV1, NextGenerationOptionsV1, WeaknessPriorityV1


class ReportRadar(BaseModel):
    dimensions: List[str]
    values: List[float]


class DifficultyCurveItem(BaseModel):
    topic: str
    score: float
    recommended_difficulty: str


class BlindSpotNodeV1(BaseModel):
    skill_node_id: str
    name: str
    stable_order: int
    prerequisite_ids: List[str] = Field(default_factory=list)


class BlindSpotCellV1(BaseModel):
    skill_node_id: str
    dimension: Literal["concept", "scenario", "misconception", "practice"]
    score: float | None = Field(default=None, ge=0.0, le=1.0)
    status: Literal["verified_weak", "learning", "mastered", "needs_evidence", "unassessed"]
    confidence: str
    objective_evidence_count: int = Field(ge=0)
    reason_codes: List[str] = Field(default_factory=list)


class KnowledgeBlindSpotMapV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    dimensions: List[Literal["concept", "scenario", "misconception", "practice"]]
    nodes: List[BlindSpotNodeV1] = Field(default_factory=list)
    cells: List[BlindSpotCellV1] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class ResourceDifficultyPointV1(BaseModel):
    resource_id: str
    skill_node_id: str
    skill_name: str
    learner_readiness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    resource_difficulty_score: float | None = Field(default=None, ge=0.0, le=1.0)
    difficulty_gap: float | None = Field(default=None, ge=-1.0, le=1.0)
    match_status: Literal["too_easy", "matched", "challenging", "too_hard", "not_measured"]
    confidence: str
    difficulty_source: Literal["declared_band", "deterministic_features", "calibrated_history", "unavailable"]
    resource_type: str
    resource_ids: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)


class ResourceDifficultyCurveV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    strategy_version: str
    points: List[ResourceDifficultyPointV1] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class LearningPathGraphNodeV1(BaseModel):
    skill_node_id: str
    name: str
    progress_status: str
    mastery_status: str
    mastery_score: float | None = Field(default=None, ge=0.0, le=1.0)
    confidence: str
    role: Literal["prerequisite", "current", "remedial", "next", "challenge", "verification"]
    blocked: bool
    blocked_by_node_ids: List[str] = Field(default_factory=list)
    recommended_resource_types: List[str] = Field(default_factory=list)
    reason_codes: List[str] = Field(default_factory=list)
    stable_order: int


class LearningPathGraphEdgeV1(BaseModel):
    source_skill_node_id: str
    target_skill_node_id: str
    relation: Literal["prerequisite", "remedial", "next", "challenge", "verification"]


class LearningPathGraphV1(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    path_id: str | None = None
    path_version: int | None = Field(default=None, ge=1)
    nodes: List[LearningPathGraphNodeV1] = Field(default_factory=list)
    edges: List[LearningPathGraphEdgeV1] = Field(default_factory=list)
    current_node_ids: List[str] = Field(default_factory=list)
    recommended_next_node_ids: List[str] = Field(default_factory=list)
    summary: Dict[str, Any] = Field(default_factory=dict)


class ReportRevisionPartsV1(BaseModel):
    """Stable, non-sensitive revision inputs for the Report 3.0 projection."""

    profile: str
    mastery: str
    activity: str
    text_resources: str
    resource_match: str = ""
    path: str = ""


class ReportResponse(BaseModel):
    # Keep the original fields below intact: report 3.0 is deliberately an
    # additive read contract for existing report consumers.
    report_schema_version: str = "3.0"
    report_revision: Optional[str] = None
    data_as_of: Optional[datetime] = None
    window: Dict[str, Any] = Field(default_factory=dict)
    freshness: Dict[str, Any] = Field(default_factory=dict)
    learning_activity: Dict[str, Any] = Field(default_factory=dict)
    mastery_overview: Dict[str, Any] = Field(default_factory=dict)
    mastery_trends: List[Dict[str, Any]] = Field(default_factory=list)
    weakness_groups: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)
    resource_credibility_summary: Dict[str, Any] = Field(default_factory=dict)
    recent_resource_credibility: List[Dict[str, Any]] = Field(default_factory=list)
    as_of_profile_version: int = 1
    generated_at: datetime
    learner_id: str
    radar: ReportRadar
    weak_points: List[str]
    strong_points: List[str]
    skill_level: str
    learning_goal: str
    difficulty_curve: List[DifficultyCurveItem]
    learning_path: List[LearningPathItem] = Field(default_factory=list)
    blind_spot_heatmap: List[Dict[str, Any]] = Field(default_factory=list)
    agent_flow: List[AgentTrace] = Field(default_factory=list)
    resource_difficulty_match: List[Dict[str, Any]] = Field(default_factory=list)
    review_summary: Dict[str, Any] = Field(default_factory=dict)
    feedback_trend: List[Dict[str, Any]] = Field(default_factory=list)
    metric_summary: Dict[str, Any] = Field(default_factory=dict)
    next_suggestions: List[str] = Field(default_factory=list)
    recent_resources: List[LearningResource] = Field(default_factory=list)
    recent_feedback: List[FeedbackRecord] = Field(default_factory=list)
    profile_version: int = 1
    knowledge_mastery: Dict[str, Any] = Field(default_factory=dict)
    current_learning_path: Optional[Dict[str, Any]] = None
    recent_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    feedback_analysis: List[Dict[str, Any]] = Field(default_factory=list)
    recent_feedback_decisions: List[Dict[str, Any]] = Field(default_factory=list)
    recent_knowledge_state_mutations: List[Dict[str, Any]] = Field(default_factory=list)
    recent_followup_runs: List[Dict[str, Any]] = Field(default_factory=list)
    profile_versions: List[Dict[str, Any]] = Field(default_factory=list)
    ability_nodes: List[AbilityNodeProjectionV1] = Field(default_factory=list)
    mastery_summary: Dict[str, Any] = Field(default_factory=dict)
    mastery_trend: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_coverage: Dict[str, Any] = Field(default_factory=dict)
    weakness_priorities: List[WeaknessPriorityV1] = Field(default_factory=list)
    next_resource_focus: Dict[str, Any] = Field(default_factory=dict)
    generation_options: NextGenerationOptionsV1 | None = None
    tier_progress: Dict[str, Any] = Field(default_factory=dict)
    knowledge_blind_spot_map: KnowledgeBlindSpotMapV1 | None = None
    resource_difficulty_curve: ResourceDifficultyCurveV1 | None = None
    learning_path_graph: LearningPathGraphV1 | None = None
    data_warnings: List[str] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    sample_count: int
    metrics: Dict[str, float]
    ablation: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None


__all__ = [
    "BlindSpotCellV1",
    "BlindSpotNodeV1",
    "DifficultyCurveItem",
    "EvaluationSummary",
    "KnowledgeBlindSpotMapV1",
    "LearningPathGraphEdgeV1",
    "LearningPathGraphNodeV1",
    "LearningPathGraphV1",
    "ReportRadar",
    "ReportResponse",
    "ReportRevisionPartsV1",
    "ResourceDifficultyCurveV1",
    "ResourceDifficultyPointV1",
]
