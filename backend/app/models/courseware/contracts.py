"""Public contracts for the isolated interactive-courseware workflow."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


CoursewareJobState = Literal[
    "queued", "admitting", "snapshotting", "design_reviewing", "composing",
    "trace_reviewing", "quality_reviewing", "rendering", "validating", "publishing",
    "approved_pending_publish", "published", "published_with_warnings", "rejected_admission", "failed",
]


class CoursewareJobCreateRequest(BaseModel):
    learner_id: str = Field(min_length=1, max_length=64)
    source_resource_ids: list[str] = Field(min_length=1, max_length=8)
    title: str | None = Field(default=None, max_length=160)
    publish_mode: Literal["manual", "automatic"] = "manual"
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
    publish_mode: Literal["manual", "automatic"] = "manual"
    resource_id: str | None = None
    warnings: list[dict[str, str]] = Field(default_factory=list)
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
    error_code: str | None = None
    error_message: str | None = None


class CoursewareJobDetail(CoursewareJobResponse):
    scenes: list[CoursewareSceneStatus] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)


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
    mime_type: str = "text/html"
    artifact_sha256: str
    artifact_size: int
    source_summary: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, str]] = Field(default_factory=list)
    created_at: datetime | None = None
    published_at: datetime | None = None
