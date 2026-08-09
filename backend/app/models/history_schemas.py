from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.models.schemas import LearnerProfile


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
