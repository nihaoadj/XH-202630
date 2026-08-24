"""Shared read-model contract for the unified resource library."""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class ResourceLibraryItem(BaseModel):
    id: str
    resource_kind: Literal["text", "interactive_courseware"]
    title: str
    topic: str | None = None
    learner_id: str
    created_at: datetime | None = None
    published_at: datetime | None = None
    version: int = 1
    status: str = "published"
    preview_capability: bool = True
    download_capability: bool = False
    source_summary: list[dict[str, Any]] = Field(default_factory=list)
    run_id: str | None = None
    batch_id: str | None = None
    resource_type: str | None = None
    difficulty: str | None = None
    knowledge_points: list[str] = Field(default_factory=list)
