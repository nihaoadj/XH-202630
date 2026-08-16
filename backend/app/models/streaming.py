"""Public, bounded contracts for the read-only WorkflowEvent SSE projection."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.persistence import JsonScalar, ReplayCompleteness, RunStatus


class StrictStreamModel(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class PublicRunEvent(StrictStreamModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    event_id: str
    sequence: int = Field(ge=1)
    event_type: str
    step_id: str | None = None
    step_sequence: int | None = Field(default=None, ge=1)
    node_name: str | None = None
    status: str | None = None
    summary: str | None = None
    payload: dict[str, JsonScalar | list[JsonScalar]] = Field(default_factory=dict)
    error_code: str | None = None
    occurred_at: datetime


class PublicRunSnapshot(StrictStreamModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    run_status: RunStatus | None = None
    workflow_status: str | None = None
    current_node: str | None = None
    current_step_sequence: int = Field(default=0, ge=0)
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)
    retrieval_status: str | None = None
    final_decision: str | None = None
    replay_completeness: ReplayCompleteness | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    ended_at: datetime | None = None
    last_event_sequence: int = Field(default=0, ge=0)
    job_status: Literal["queued", "running", "completed", "failed"] | None = None
    is_terminal: bool = False


class PublicStreamPing(StrictStreamModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    last_event_sequence: int = Field(ge=0)
    server_time: datetime


class PublicStreamError(StrictStreamModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    code: str
    message: str
    last_event_sequence: int = Field(ge=0)
