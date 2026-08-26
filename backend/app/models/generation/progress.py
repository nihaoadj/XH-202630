"""Public contracts for asynchronous learning-document generation progress."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field


class ResourceRepresentation(str, Enum):
    TEXT = "text"


class ResourceExecutionState(str, Enum):
    QUEUED = "queued"
    GENERATING = "generating"
    GENERATED = "generated"
    REVIEWING = "reviewing"
    REVISION_REQUESTED = "revision_requested"
    CLAIM_CHECKING = "claim_checking"
    APPROVED = "approved"
    HUMAN_REVIEW = "human_review"
    FAILED = "failed"


class ResourceExecutionProgress(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    resource_spec_id: str
    resource_type: str
    representation: ResourceRepresentation = ResourceRepresentation.TEXT
    resource_execution_state: ResourceExecutionState = ResourceExecutionState.QUEUED
    worker_step_id: Optional[str] = None
    attempt: int = Field(default=0, ge=0)
    resource_id: Optional[str] = None
    review_id: Optional[str] = None
    error_code: Optional[str] = None
    agent_name: Optional[str] = None
    prompt_version: Optional[str] = None
    artifact_format: Optional[str] = None
    validation_status: Optional[str] = None
    renderer_version: Optional[str] = None
    publication_status: Literal["unpublished", "published"] = "unpublished"
    updated_at: Optional[datetime] = None


class RunResourceProgressSummary(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    total: int = Field(default=0, ge=0)
    counts: Dict[str, int] = Field(default_factory=dict)
    approved: int = Field(default=0, ge=0)
    human_review: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    published: int = Field(default=0, ge=0)
    can_finalize: bool = False
    items: List[ResourceExecutionProgress] = Field(default_factory=list)


__all__ = [
    "ResourceRepresentation",
    "ResourceExecutionState",
    "ResourceExecutionProgress",
    "RunResourceProgressSummary",
]
