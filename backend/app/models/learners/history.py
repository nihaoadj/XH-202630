from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.learning_documents.schemas import LearnerProfile


class DiagnosticRunRecord(BaseModel):
    diagnostic_result_id: str
    learner_id: str
    knowledge_base_id: Optional[str] = None
    ability_level: str
    weak_points: List[str] = Field(default_factory=list)
    strong_points: List[str] = Field(default_factory=list)
    knowledge_states_snapshot: Dict[str, Any] = Field(default_factory=dict)
    recommended_path: List[Dict[str, Any]] = Field(default_factory=list)
    raw_result: Dict[str, Any] = Field(default_factory=dict)
    created_at: Optional[datetime] = None


class LearningHistoryEvent(BaseModel):
    event_id: str
    event_type: str
    title: str
    description: str
    occurred_at: Optional[datetime] = None
    status: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class LearningHistoryTimelineResponse(BaseModel):
    learner_id: str
    profile: LearnerProfile
    events: List[LearningHistoryEvent] = Field(default_factory=list)


class LearningJourneyCurrentState(BaseModel):
    """Learner-facing projection of the current durable learning state."""

    path_id: Optional[str] = None
    path_version: Optional[int] = None
    current_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    completed_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    upcoming_nodes: List[Dict[str, Any]] = Field(default_factory=list)
    mastery: List[Dict[str, Any]] = Field(default_factory=list)
    next_action: Optional[str] = None
    latest_assessment: Optional[Dict[str, Any]] = None


class LearningJourneyRound(BaseModel):
    """One resource-batch learning round, with only safe display fields."""

    run_id: str
    batch_id: Optional[str] = None
    run_ids: List[str] = Field(default_factory=list)
    round_id: Optional[str] = None
    topic: str
    status: str
    occurred_at: Optional[datetime] = None
    is_followup: bool = False
    parent_run_id: Optional[str] = None
    resources: List[Dict[str, Any]] = Field(default_factory=list)
    assessment: Optional[Dict[str, Any]] = None
    feedback: Optional[Dict[str, Any]] = None
    path_change: Optional[Dict[str, Any]] = None
    run_summary: Dict[str, Any] = Field(default_factory=dict)


class LearningJourneyResponse(BaseModel):
    """Read-only full-chain view.  Legacy facts remain separate rather than guessed."""

    learner_id: str
    profile: LearnerProfile
    current_state: LearningJourneyCurrentState
    rounds: List[LearningJourneyRound] = Field(default_factory=list)
    unlinked_events: List[LearningHistoryEvent] = Field(default_factory=list)
    total_rounds: int = 0
    next_offset: Optional[int] = None
