"""Versioned learner events emitted by offline courseware runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CoursewareEventType = Literal[
    "scene_viewed", "scene_completed", "answer_submitted", "answer_correct",
    "answer_retry", "hint_opened", "courseware_completed",
    "flashcard_flipped", "flashcard_known", "flashcard_review",
    "matching_attempt", "ordering_submitted",
]


class CoursewareLearningEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(min_length=1, max_length=160)
    event_schema_version: Literal["1.0"] = "1.0"
    occurrence_id: str | None = Field(default=None, max_length=160)
    event_type: CoursewareEventType
    resource_id: str = Field(min_length=1, max_length=128)
    release_id: str = Field(min_length=1, max_length=128)
    resource_version: int = Field(default=1, ge=1)
    release_version: int = Field(default=1, ge=1)
    scene_id: str | None = Field(default=None, max_length=128)
    scene_version: str = Field(default="1.0", max_length=16)
    component_id: str | None = Field(default=None, max_length=128)
    component_version: str = Field(default="1.0", max_length=16)
    state: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CoursewareLearningEventBatch(BaseModel):
    events: list[CoursewareLearningEvent] = Field(min_length=1, max_length=100)


__all__ = ["CoursewareEventType", "CoursewareLearningEvent"]
