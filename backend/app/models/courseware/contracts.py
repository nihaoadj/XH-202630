"""Public contracts for the isolated interactive-courseware workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator



CoursewareJobState = Literal[
    "queued", "admitting", "snapshotting", "design_reviewing", "composing",
    "trace_reviewing", "quality_reviewing", "auto_revising", "rendering", "validating", "publishing",
    "approved_pending_publish", "published", "published_with_warnings", "rejected_admission", "failed",
    "quarantined", "release_blocked", "cancelled", "timed_out",
]


class CoursewareJobCreateRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64)
    source_resource_ids: list[str] = Field(min_length=1, max_length=8)
    title: str | None = Field(default=None, max_length=160)
    learning_goal: str | None = Field(default=None, max_length=240)
    expected_duration_minutes: int | None = Field(default=None, ge=5, le=240)
    interaction_intensity: Literal["low", "medium", "high"] = "medium"
    visual_style_id: Literal["editorial", "midnight", "paper"] | None = None
    # ``manual`` remains accepted only for requests persisted before the
    # automation rollout. New work is always released by the quality gates.
    publish_mode: Literal["manual", "automatic"] = "automatic"
    idempotency_key: str | None = Field(default=None, max_length=128)

    @field_validator("source_resource_ids")
    @classmethod
    def unique_source_ids(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned or len(cleaned) != len(value) or len(cleaned) != len(set(cleaned)):
            raise ValueError("source_resource_ids 必须是非空且不重复的资源 ID")
        return cleaned


class CoursewareJobResponse(BaseModel):
    run_id: str
    learner_id: str
    status: CoursewareJobState
    title: str | None = None
    publish_mode: Literal["manual", "automatic"] = "automatic"
    resource_id: str | None = None
    request_options: dict[str, Any] = Field(default_factory=dict)
    quality_summary: dict[str, Any] = Field(default_factory=dict)
    # Warning payloads may carry machine-readable flags (for example
    # ``discarded_candidate``) in addition to human-readable strings.
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class CoursewareSceneStatus(BaseModel):
    scene_id: str
    scene_order: int
    kind: str
    title: str | None = None
    status: str
    attempt: int = 0
    input_snapshot_hash: str | None = None
    agent_version: str | None = None
    prompt_version: str | None = None
    review_instruction: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class CoursewareJobDetail(CoursewareJobResponse):
    scenes: list[CoursewareSceneStatus] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    scene_revisions: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)


class CoursewareEvent(BaseModel):
    event_id: str
    run_id: str
    event_sequence: int
    stage: str
    scene_id: str | None = None
    status: str
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime | None = None


class CoursewareResourceDetail(BaseModel):
    resource_id: str
    learner_id: str
    run_id: str
    title: str
    topic: str
    status: Literal["approved_pending_publish", "published", "stale"]
    version: int = 1
    released_release_id: str | None = None
    mime_type: str = "text/html"
    artifact_sha256: str
    artifact_size: int
    source_summary: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime | None = None
    published_at: datetime | None = None
