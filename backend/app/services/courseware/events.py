"""Idempotent learning-event ingestion and read-only progress projection."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import uuid4

from app.core.events import event_id
from app.models.courseware.events import CoursewareLearningEvent, sanitize_event_state


class CoursewareEventProjector:
    """Small deterministic projection used by API workers and offline replay.

    It stores only allow-listed learning state, never submitted answer text or
    other raw learner input.  A release ID is part of the event identity so an
    old release cannot advance a new release's projection.
    """

    def __init__(self) -> None:
        self._events: dict[str, CoursewareLearningEvent] = {}

    def record(self, event: CoursewareLearningEvent | Mapping[str, Any]) -> CoursewareLearningEvent:
        value = event if isinstance(event, CoursewareLearningEvent) else CoursewareLearningEvent.model_validate(event)
        safe_state = sanitize_event_state(value.state)
        value = value.model_copy(update={"state": safe_state, "occurrence_id": value.occurrence_id or value.event_id})
        existing = self._events.get(value.event_id)
        if existing is not None:
            return existing
        self._events[value.event_id] = value
        return value

    def record_runtime(
        self, event_type: str, *, resource_id: str, release_id: str, scene_id: str | None = None,
        component_id: str | None = None, component_version: str = "1.0", state: Mapping[str, Any] | None = None,
    ) -> CoursewareLearningEvent:
        payload = {
            "event_type": event_type, "resource_id": resource_id, "release_id": release_id,
            "scene_id": scene_id, "component_id": component_id, "component_version": component_version,
            "state": sanitize_event_state(state),
        }
        occurrence_id = f"occ_{uuid4().hex}"
        return self.record(CoursewareLearningEvent(
            event_id=occurrence_id, occurrence_id=occurrence_id, **payload,
        ))

    def replay(self, events: Iterable[CoursewareLearningEvent | Mapping[str, Any]]) -> int:
        before = len(self._events)
        for item in events:
            self.record(item)
        return len(self._events) - before

    def events(self, *, resource_id: str | None = None, release_id: str | None = None) -> list[CoursewareLearningEvent]:
        values = [item for item in self._events.values()
                  if (resource_id is None or item.resource_id == resource_id)
                  and (release_id is None or item.release_id == release_id)]
        return sorted(values, key=lambda item: (item.created_at, item.event_id))

    def progress(self, *, resource_id: str, release_id: str) -> dict[str, Any]:
        values = self.events(resource_id=resource_id, release_id=release_id)
        viewed = {item.scene_id for item in values if item.event_type == "scene_viewed" and item.scene_id}
        completed = {item.scene_id for item in values if item.event_type == "scene_completed" and item.scene_id}
        current_scene_id = next((item.scene_id for item in reversed(values) if item.scene_id and item.event_type == "scene_viewed"), None)
        current_scene_index = next(
            (item.state.get("scene_index") for item in reversed(values)
             if item.event_type == "scene_viewed" and isinstance(item.state.get("scene_index"), int)),
            None,
        )
        component_state: dict[str, Any] = {}
        for item in values:
            if item.state.get("component_state"):
                component_state.update(item.state["component_state"])
        return {
            "resource_id": resource_id, "release_id": release_id,
            "viewed_scene_ids": sorted(viewed), "completed_scene_ids": sorted(completed),
            "courseware_completed": any(item.event_type == "courseware_completed" for item in values),
            "answer_count": sum(item.event_type == "answer_submitted" for item in values),
            "current_scene_id": current_scene_id, "current_scene_index": current_scene_index,
            "component_state": component_state,
        }


__all__ = ["CoursewareEventProjector"]
