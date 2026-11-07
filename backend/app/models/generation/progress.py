"""Public contracts for asynchronous learning-document generation progress."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class RoundBindingSummaryV1(BaseModel):
    """Read-only job binding resolved by the server from persisted facts."""

    round_id: str = Field(min_length=1, max_length=128)
    member_id: str = Field(min_length=1, max_length=128)
    stage_id: str = Field(min_length=1, max_length=128)
    stage_node_id: str = Field(min_length=1, max_length=128)
    role: Literal["primary", "review", "legacy"]


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


class PublishCompleteness(str, Enum):
    """How completely the derived publication facts cover the requested run."""

    COMPLETE = "complete"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class PublishIncompleteReason(str, Enum):
    """Controlled reasons why a publication summary is not complete."""

    REQUEST_MISSING = "request_missing"
    SPEC_REQUEST_MISMATCH = "spec_request_mismatch"
    LOGICAL_IDENTITY_MISSING = "logical_identity_missing"
    RESOURCE_REFERENCE_MISSING = "resource_reference_missing"
    UNSUPPORTED_REPRESENTATION = "unsupported_representation"
    REPOSITORY_UNAVAILABLE = "repository_unavailable"
    LINEAGE_CONFLICT = "lineage_conflict"


class RunPublishSummary(BaseModel):
    """Read-only publication facts for one run, derived from persisted state.

    Counters are logical resources, not executions or versions.  ``None`` means
    "cannot be confirmed", never zero; ``completeness`` describes the data, not
    the job lifecycle state.
    """

    schema_version: Literal["1.0"] = "1.0"
    total: Optional[int] = Field(default=None, ge=0)
    published: Optional[int] = Field(default=None, ge=0)
    unpublished: Optional[int] = Field(default=None, ge=0)
    pending_review: Optional[int] = Field(default=None, ge=0)
    completeness: PublishCompleteness = PublishCompleteness.UNAVAILABLE
    incomplete_reasons: List[PublishIncompleteReason] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_complete_counters(self) -> "RunPublishSummary":
        if self.completeness is not PublishCompleteness.COMPLETE:
            return self
        total, published = self.total, self.published
        unpublished, pending = self.unpublished, self.pending_review
        if total is None or published is None or unpublished is None or pending is None:
            raise ValueError("complete publish summary requires every counter")
        if published + unpublished != total:
            raise ValueError("complete publish summary requires published + unpublished == total")
        if not 0 <= pending <= unpublished:
            raise ValueError("pending_review must be a subset of unpublished")
        if self.incomplete_reasons:
            raise ValueError("complete publish summary cannot carry incomplete reasons")
        return self


__all__ = [
    "ResourceRepresentation",
    "ResourceExecutionState",
    "ResourceExecutionProgress",
    "RunResourceProgressSummary",
    "PublishCompleteness",
    "PublishIncompleteReason",
    "RunPublishSummary",
]
