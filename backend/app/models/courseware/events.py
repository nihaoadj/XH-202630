"""Versioned learner events emitted by offline courseware runtime."""

from __future__ import annotations

from datetime import datetime, timezone
from collections.abc import Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


CoursewareEventType = Literal[
    "scene_viewed", "scene_completed", "answer_submitted", "answer_correct",
    "answer_retry", "hint_opened", "courseware_completed",
    "flashcard_flipped", "flashcard_known", "flashcard_review",
    "matching_attempt", "ordering_submitted", "review_answer_revealed", "review_self_assessed",
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


def sanitize_component_state(value: Any) -> dict[str, Any]:
    """Keep only bounded, named runtime state; never persist learner answers."""
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    flashcard = value.get("flashcard")
    if isinstance(flashcard, Mapping) and str(flashcard.get("status")) in {"front", "back", "known", "review"}:
        result["flashcard"] = {"status": str(flashcard["status"])}
    matching = value.get("matching")
    if isinstance(matching, Mapping):
        item = matching.get("selected_item_id")
        pair_ids = matching.get("matched_pair_ids")
        state: dict[str, Any] = {}
        if isinstance(item, str) and 0 < len(item) <= 64:
            state["selected_item_id"] = item
        if isinstance(pair_ids, list):
            clean = [item for item in pair_ids if isinstance(item, str) and 0 < len(item) <= 64]
            if len(clean) == len(set(clean)) and len(clean) <= 16:
                state["matched_pair_ids"] = clean
        if isinstance(matching.get("completed"), bool):
            state["completed"] = matching["completed"]
        if state:
            result["matching"] = state
    ordering = value.get("ordering")
    if isinstance(ordering, Mapping):
        order = ordering.get("order")
        state = {}
        if isinstance(order, list):
            clean = [item for item in order if isinstance(item, str) and 0 < len(item) <= 64]
            if len(clean) == len(order) and len(clean) == len(set(clean)) and len(clean) <= 16:
                state["order"] = clean
        for key in ("submitted", "correct"):
            if isinstance(ordering.get(key), bool):
                state[key] = ordering[key]
        if state:
            result["ordering"] = state
    review = value.get("review_practice")
    if isinstance(review, Mapping):
        question_id = review.get("question_id")
        state = {}
        if isinstance(question_id, str) and 0 < len(question_id) <= 64:
            state["question_id"] = question_id
        if isinstance(review.get("revealed"), bool):
            state["revealed"] = review["revealed"]
        if str(review.get("self_rating")) in {"known", "uncertain", "not_known"}:
            state["self_rating"] = str(review["self_rating"])
        if state:
            result["review_practice"] = state
    return result


def sanitize_event_state(
    value: Any, *, scene_id: str | None = None, component_id: str | None = None,
    component_version: str = "1.0",
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    safe_keys = {"scene_index", "scene_count", "correct", "completed", "attempt", "duration_ms"}
    result = {key: value[key] for key in safe_keys if key in value and isinstance(value[key], (bool, int, float))}
    component_state = sanitize_component_state(value.get("component_state"))
    if component_state and scene_id and component_id:
        result["component_state"] = {
            scene_id: {component_id: {"component_version": component_version, "value": component_state}}
        }
    return result


__all__ = ["CoursewareEventType", "CoursewareLearningEvent", "sanitize_component_state", "sanitize_event_state"]
