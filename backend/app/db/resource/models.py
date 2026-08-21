"""Persistence DTOs for resource specifications and execution projections."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


ResourceRepresentationValue = Literal["text"]
ResourceExecutionStateValue = Literal[
    "queued",
    "generating",
    "generated",
    "reviewing",
    "revision_requested",
    "claim_checking",
    "approved",
    "human_review",
    "failed",
]


class ResourceSpecRecord(BaseModel):
    """Frozen resource work item stored independently from workflow internals."""

    schema_version: Literal["1.0"] = "1.0"
    resource_spec_id: str = Field(min_length=1, max_length=64)
    run_id: str = Field(min_length=1, max_length=128)
    resource_family_id: str | None = Field(default=None, max_length=64)
    resource_type: str = Field(min_length=1, max_length=32)
    learning_objective: str = Field(min_length=1)
    knowledge_points: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    difficulty: str = Field(min_length=1, max_length=16)
    representations: list[dict[str, Any]] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    display_order: int = Field(default=0, ge=0)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def fill_family_and_validate_representations(self) -> "ResourceSpecRecord":
        if not self.resource_family_id:
            self.resource_family_id = self.resource_spec_id
        seen: set[str] = set()
        for representation in self.representations:
            value = str(representation.get("representation") or "").strip()
            if value != "text":
                raise ValueError("representation must be text")
            if value in seen:
                raise ValueError("representations must be unique within a resource spec")
            seen.add(value)
        if not seen:
            raise ValueError("resource spec requires at least one representation")
        return self


class ResourceExecutionRecord(BaseModel):
    """Latest state of one ``(run, spec, representation)`` execution."""

    schema_version: Literal["1.0"] = "1.0"
    execution_id: str | None = Field(default=None, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    resource_spec_id: str = Field(min_length=1, max_length=64)
    resource_type: str = Field(min_length=1, max_length=32)
    representation: ResourceRepresentationValue = "text"
    worker_step_id: str | None = Field(default=None, max_length=64)
    state: ResourceExecutionStateValue = "queued"
    attempt: int = Field(default=0, ge=0)
    resource_id: str | None = Field(default=None, max_length=64)
    review_id: str | None = Field(default=None, max_length=128)
    error_code: str | None = Field(default=None, max_length=128)
    agent_name: str = Field(min_length=1, max_length=128)
    prompt_version: str = Field(min_length=1, max_length=64)
    artifact_format: str = Field(min_length=1, max_length=64)
    validation_status: str = Field(default="pending", min_length=1, max_length=32)
    renderer_version: str | None = Field(default=None, max_length=64)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def fill_execution_id(self) -> "ResourceExecutionRecord":
        if not self.execution_id:
            identity = f"{self.run_id}\0{self.resource_spec_id}\0{self.representation}"
            self.execution_id = f"rex_{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
        return self
