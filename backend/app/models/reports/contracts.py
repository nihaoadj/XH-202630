"""Public DTOs for learning reports and evaluation summaries."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.learning_documents.schemas import (
    AgentTrace,
    FeedbackRecord,
    LearningPathItem,
    LearningResource,
)
from app.models.learners.mastery import AbilityNodeProjectionV1, WeaknessPriorityV1


class ReportRadar(BaseModel):
    dimensions: List[str]
    values: List[float]


class DifficultyCurveItem(BaseModel):
    topic: str
    score: float
    recommended_difficulty: str


class ReportResponse(BaseModel):
    report_schema_version: str = "2.0"
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
    data_warnings: List[str] = Field(default_factory=list)


class EvaluationSummary(BaseModel):
    sample_count: int
    metrics: Dict[str, float]
    ablation: List[Dict[str, Any]] = Field(default_factory=list)
    created_at: Optional[datetime] = None


__all__ = ["ReportRadar", "DifficultyCurveItem", "ReportResponse", "EvaluationSummary"]
