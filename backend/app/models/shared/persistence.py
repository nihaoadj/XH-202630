"""Versioned, sanitized contracts for durable Agent workflow persistence."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.retrieval.knowledge_ids import normalize_text, sha256_hex
from app.models.knowledge.knowledge import EvidenceItem, SourceLocator


PERSISTENCE_SCHEMA_VERSION = "1.0"
JsonScalar: TypeAlias = str | int | float | bool | None


class StrictPersistenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid", protected_namespaces=())


class RunStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    HUMAN_REVIEW = "human_review"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


TERMINAL_RUN_STATUSES = frozenset(
    {
        RunStatus.COMPLETED,
        RunStatus.DEGRADED,
        RunStatus.HUMAN_REVIEW,
        RunStatus.FAILED,
        RunStatus.INTERRUPTED,
    }
)

RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.CREATED: frozenset({RunStatus.RUNNING}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.FINALIZING, RunStatus.FAILED, RunStatus.INTERRUPTED}
    ),
    RunStatus.FINALIZING: frozenset(
        {
            RunStatus.COMPLETED,
            RunStatus.DEGRADED,
            RunStatus.HUMAN_REVIEW,
            RunStatus.FAILED,
            RunStatus.INTERRUPTED,
        }
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.DEGRADED: frozenset(),
    RunStatus.HUMAN_REVIEW: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.INTERRUPTED: frozenset(),
}


def require_run_transition(current: RunStatus | str, target: RunStatus | str) -> None:
    current_status = RunStatus(current)
    target_status = RunStatus(target)
    if current_status == target_status:
        return
    if target_status not in RUN_TRANSITIONS[current_status]:
        raise ValueError(f"illegal run transition: {current_status.value}->{target_status.value}")


class WorkflowEventType(str, Enum):
    RUN_CREATED = "run_created"
    RUN_STARTED = "run_started"
    STEP_STARTED = "step_started"
    STEP_SUCCEEDED = "step_succeeded"
    STEP_DEGRADED = "step_degraded"
    STEP_FAILED = "step_failed"
    EVIDENCE_SNAPSHOT_SAVED = "evidence_snapshot_saved"
    CHECKPOINT_SAVED = "checkpoint_saved"
    RUN_FINALIZING = "run_finalizing"
    RESOURCE_PERSISTED = "resource_persisted"
    WORKFLOW_FINALIZATION_FAILED = "workflow_finalization_failed"
    RESOURCE_VERSION_CREATED = "resource_version_created"
    REVIEW_PERSISTED = "review_persisted"
    REVISION_REQUESTED = "revision_requested"
    CLAIM_EXTRACTION_STARTED = "claim_extraction_started"
    CLAIM_EXTRACTION_COMPLETED = "claim_extraction_completed"
    CLAIM_JUDGEMENT_COMPLETED = "claim_judgement_completed"
    CLAIM_REVIEW_FAILED = "claim_review_failed"
    CLAIM_METRIC_COMPUTED = "claim_metric_computed"
    ATTEMPT_SUBMITTED = "attempt_submitted"
    FEEDBACK_DECISION_STARTED = "feedback_decision_started"
    FEEDBACK_DECISION_COMPLETED = "feedback_decision_completed"
    KNOWLEDGE_STATE_UPDATED = "knowledge_state_updated"
    PROFILE_UPDATED = "profile_updated"
    PATH_MUTATED = "path_mutated"
    FOLLOWUP_GENERATION_CREATED = "followup_generation_created"
    FOLLOWUP_GENERATION_FAILED = "followup_generation_failed"
    RESOURCE_PUBLISHED = "resource_published"
    RESOURCE_EXECUTION_QUEUED = "resource_execution_queued"
    RESOURCE_GENERATION_STARTED = "resource_generation_started"
    RESOURCE_GENERATED = "resource_generated"
    RESOURCE_HUMAN_REVIEW_REQUESTED = "resource_human_review_requested"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_INTERRUPTED = "run_interrupted"


class ReplayCompleteness(str, Enum):
    COMPLETE = "complete"
    LEGACY_PARTIAL = "legacy_partial"


class LLMAttemptRecord(StrictPersistenceModel):
    attempt: int = Field(ge=1)
    status: str = Field(min_length=1, max_length=32)
    error_code: str | None = Field(default=None, max_length=128)
    latency_ms: int = Field(ge=0)
    structured_output_mode: str = Field(min_length=1, max_length=32)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class AgentRunRecord(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    run_id: str = Field(min_length=1, max_length=128)
    learner_id: str | None = Field(default=None, max_length=64)
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    topic: str | None = Field(default=None, max_length=512)
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    status: RunStatus
    workflow_status: str | None = Field(default=None, max_length=32)
    execution_status: str | None = Field(default=None, max_length=32)
    current_node: str | None = Field(default=None, max_length=128)
    current_step_id: str | None = Field(default=None, max_length=128)
    current_step_sequence: int = Field(default=0, ge=0)
    last_event_sequence: int = Field(default=0, ge=0)
    generation_attempt: int = Field(default=1, ge=1)
    revision_count: int = Field(default=0, ge=0)
    retrieval_status: str | None = Field(default=None, max_length=32)
    final_decision: str | None = Field(default=None, max_length=256)
    last_error_code: str | None = Field(default=None, max_length=128)
    replay_completeness: ReplayCompleteness = ReplayCompleteness.COMPLETE
    owner_instance_id: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    heartbeat_at: datetime | None = None
    started_at: datetime | None = None
    updated_at: datetime
    ended_at: datetime | None = None
    row_version: int = Field(default=1, ge=1)


class RunSummary(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    run_id: str
    status: RunStatus
    workflow_status: str | None = None
    execution_status: str | None = None
    learner_id: str | None = None
    knowledge_base_id: str | None = None
    topic: str | None = None
    current_node: str | None = None
    current_step_sequence: int = 0
    generation_attempt: int = 1
    revision_count: int = 0
    retrieval_status: str | None = None
    final_decision: str | None = None
    last_error_code: str | None = None
    started_at: datetime | None = None
    updated_at: datetime
    ended_at: datetime | None = None
    replay_completeness: ReplayCompleteness

    @classmethod
    def from_record(cls, record: AgentRunRecord) -> "RunSummary":
        return cls.model_validate(
            record.model_dump(
                include=set(cls.model_fields),
                mode="python",
            )
        )


class AgentStepRecord(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    step_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    step_sequence: int = Field(ge=1)
    agent_name: str = Field(min_length=1, max_length=128)
    node_name: str = Field(min_length=1, max_length=128)
    action: str = Field(min_length=1, max_length=256)
    status: str = Field(min_length=1, max_length=32)
    generation_attempt: int = Field(default=1, ge=1)
    input_summary: str | None = Field(default=None, max_length=2000)
    output_summary: str | None = Field(default=None, max_length=2000)
    decision_reason: str | None = Field(default=None, max_length=4000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    resource_ids: list[str] = Field(default_factory=list, max_length=100)
    review_ids: list[str] = Field(default_factory=list, max_length=100)
    retry_count: int = Field(default=0, ge=0)
    error_code: str | None = Field(default=None, max_length=128)
    error_message: str | None = Field(default=None, max_length=512)
    llm_call_id: str | None = Field(default=None, max_length=128)
    model_name: str | None = Field(default=None, max_length=128)
    provider_request_id: str | None = Field(default=None, max_length=256)
    structured_output_mode: str | None = Field(default=None, max_length=32)
    finish_reason: str | None = Field(default=None, max_length=64)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    llm_duration_ms: int | None = Field(default=None, ge=0)
    llm_attempts: list[LLMAttemptRecord] = Field(default_factory=list, max_length=10)
    retrieval_status: str | None = Field(default=None, max_length=32)
    retrieval_config_hash: str | None = None
    retrieval_query_hashes: list[str] = Field(default_factory=list, max_length=10)
    retrieval_candidate_count: int | None = Field(default=None, ge=0)
    retrieval_dropped_candidate_count: int | None = Field(default=None, ge=0)
    retrieval_partial_failure_count: int | None = Field(default=None, ge=0)
    retrieval_profile: dict[str, Any] = Field(default_factory=dict)
    workflow_elapsed_ms: int | None = Field(default=None, ge=0)
    workflow_remaining_ms: int | None = Field(default=None, ge=0)
    payload_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    started_at: datetime
    ended_at: datetime | None = None
    duration_ms: int | None = Field(default=None, ge=0)


class WorkflowEvent(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    event_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    event_sequence: int = Field(ge=1)
    event_type: WorkflowEventType
    step_id: str | None = Field(default=None, max_length=128)
    step_sequence: int | None = Field(default=None, ge=1)
    node_name: str | None = Field(default=None, max_length=128)
    status: str | None = Field(default=None, max_length=32)
    payload: dict[str, JsonScalar | list[JsonScalar]] = Field(default_factory=dict)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    error_code: str | None = Field(default=None, max_length=128)
    occurred_at: datetime
    persisted_at: datetime | None = None

    @field_validator("payload")
    @classmethod
    def validate_payload(cls, value: dict[str, Any]) -> dict[str, Any]:
        forbidden = {
            "prompt",
            "messages",
            "raw_response",
            "response_body",
            "authorization",
            "api_key",
            "query",
            "learner_profile",
            "content_text",
        }
        if any(key.lower() in forbidden for key in value):
            raise ValueError("event payload contains a forbidden field")
        if len(canonical_json(value).encode("utf-8")) > 16_384:
            raise ValueError("event payload exceeds maximum size")
        return value


class WorkflowCheckpoint(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    checkpoint_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    event_sequence: int = Field(ge=1)
    step_id: str = Field(min_length=1, max_length=128)
    step_sequence: int = Field(ge=1)
    node_name: str = Field(min_length=1, max_length=128)
    state_projection: dict[str, Any]
    state_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime

    @model_validator(mode="after")
    def validate_hash(self) -> "WorkflowCheckpoint":
        if canonical_hash(self.state_projection) != self.state_hash:
            raise ValueError("checkpoint state_hash mismatch")
        return self


class WorkflowCheckpointSummary(StrictPersistenceModel):
    checkpoint_id: str
    event_sequence: int
    step_id: str
    step_sequence: int
    node_name: str
    state_hash: str
    created_at: datetime


class PersistedEvidenceSnapshot(StrictPersistenceModel):
    schema_version: Literal["1.0"] = PERSISTENCE_SCHEMA_VERSION
    evidence_id: str = Field(min_length=1, max_length=128)
    run_id: str = Field(min_length=1, max_length=128)
    retrieval_step_id: str = Field(min_length=1, max_length=128)
    knowledge_base_id: str = Field(min_length=1, max_length=128)
    document_id: str = Field(min_length=1, max_length=128)
    document_version: str = Field(min_length=1, max_length=128)
    chunk_id: str = Field(min_length=1, max_length=128)
    query_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_rank: int = Field(ge=1)
    rank: int = Field(ge=1)
    raw_score: float
    score_kind: str
    normalized_score: float = Field(ge=0.0, le=1.0)
    excerpt: str = Field(min_length=1, max_length=10000)
    excerpt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: SourceLocator
    config_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    retrieved_at: datetime
    persisted_at: datetime | None = None

    @classmethod
    def from_evidence(
        cls,
        evidence: EvidenceItem,
        *,
        run_id: str,
        retrieval_step_id: str,
    ) -> "PersistedEvidenceSnapshot":
        payload = {
            "evidence_id": evidence.evidence_id,
            "run_id": run_id,
            "retrieval_step_id": retrieval_step_id,
            "knowledge_base_id": evidence.knowledge_base_id,
            "document_id": evidence.document_id,
            "document_version": evidence.document_version,
            "chunk_id": evidence.chunk_id,
            "query_hash": evidence.query_hash,
            "query_rank": evidence.query_rank,
            "rank": evidence.rank,
            "raw_score": evidence.raw_score,
            "score_kind": evidence.score_kind.value,
            "normalized_score": evidence.normalized_score,
            "excerpt": evidence.excerpt,
            "excerpt_hash": evidence.excerpt_hash,
            "locator": evidence.locator,
            "config_hash": evidence.config_hash,
            "retrieved_at": evidence.retrieved_at,
        }
        return cls(**payload, snapshot_hash=canonical_hash(payload))

    @model_validator(mode="after")
    def validate_identity_and_hash(self) -> "PersistedEvidenceSnapshot":
        if self.locator.knowledge_base_id != self.knowledge_base_id:
            raise ValueError("evidence locator knowledge_base_id mismatch")
        if self.locator.document_id != self.document_id:
            raise ValueError("evidence locator document_id mismatch")
        if self.locator.document_version != self.document_version:
            raise ValueError("evidence locator document_version mismatch")
        if self.locator.chunk_id != self.chunk_id:
            raise ValueError("evidence locator chunk_id mismatch")
        if sha256_hex(normalize_text(self.excerpt)) != self.excerpt_hash:
            raise ValueError("evidence excerpt_hash mismatch")
        expected = canonical_hash(
            self.model_dump(
                mode="python",
                exclude={"schema_version", "snapshot_hash", "persisted_at"},
            )
        )
        if expected != self.snapshot_hash:
            raise ValueError("evidence snapshot_hash mismatch")
        return self


class CreateRunCommand(StrictPersistenceModel):
    run_id: str = Field(min_length=1, max_length=128)
    learner_id: str | None = Field(default=None, max_length=64)
    knowledge_base_id: str | None = Field(default=None, max_length=128)
    topic: str | None = Field(default=None, max_length=512)
    request_snapshot: dict[str, Any]
    request_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    owner_instance_id: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_request_hash(self) -> "CreateRunCommand":
        if canonical_hash(self.request_snapshot) != self.request_hash:
            raise ValueError("request_hash mismatch")
        identities = {
            "learner_id": self.learner_id,
            "knowledge_base_id": self.knowledge_base_id,
            "topic": self.topic,
        }
        for key, expected in identities.items():
            if key in self.request_snapshot and self.request_snapshot[key] != expected:
                raise ValueError(f"request_snapshot {key} mismatch")
        return self


class BeginStepCommand(StrictPersistenceModel):
    run_id: str
    step_id: str
    step_sequence: int = Field(ge=1)
    node_name: str
    agent_name: str
    action: str
    generation_attempt: int = Field(default=1, ge=1)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    lease_expires_at: datetime | None = None


class CompleteStepCommand(StrictPersistenceModel):
    run_id: str
    step_id: str
    trace: dict[str, Any]
    evidence: list[PersistedEvidenceSnapshot] = Field(default_factory=list)
    ended_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class RunTimeline(StrictPersistenceModel):
    run: RunSummary
    steps: list[AgentStepRecord]
    events: list[WorkflowEvent]
    checkpoints: list[WorkflowCheckpointSummary]
    evidence: list[PersistedEvidenceSnapshot]
    resource_versions: list[dict[str, Any]] = Field(default_factory=list)
    reviews: list[dict[str, Any]] = Field(default_factory=list)
    trigger_relation: dict[str, Any] | None = None
    replay_completeness: ReplayCompleteness
    next_event_sequence: int | None = None


def _jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="python", exclude_none=True))
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc).isoformat()
    if isinstance(value, dict):
        return {
            str(key): _jsonable(item)
            for key, item in value.items()
            if item is not None
        }
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def build_checkpoint_projection(state: dict[str, Any]) -> dict[str, Any]:
    """Build the bounded allow-list projection used for read-only replay."""

    projection: dict[str, Any] = {}
    scalar_fields = (
        "schema_version",
        "run_id",
        "learner_id",
        "knowledge_base_id",
        "topic",
        "diagnostic_result_id",
        "difficulty_preference",
        "generation_mode",
        "include_review",
        "include_claim_check",
        "max_iterations",
        "workflow_status",
        "current_node",
        "generation_attempt",
        "revision_count",
        "claim_check_status",
        "retrieval_status",
        "retrieval_config_hash",
        "retrieval_candidate_count",
        "retrieval_dropped_candidate_count",
        "retrieval_partial_failure_count",
        "final_decision",
        "iteration",
    )
    for key in scalar_fields:
        value = state.get(key)
        if value is None or isinstance(value, (str, int, float, bool)):
            projection[key] = value
    for key in (
        "target_skill_nodes",
        "resource_types",
        "retrieval_query_hashes",
    ):
        projection[key] = list(state.get(key, []))[:100]
    constraints = dict(state.get("constraints", {}))
    projection["constraints"] = _jsonable(
        {
            key: constraints[key]
            for key in (
                "must_include_citations",
                "language",
                "max_length",
                "retrieval_top_k",
            )
            if key in constraints
        }
    )
    projection["diagnosis"] = _jsonable(dict(state.get("diagnosis", {})))
    projection["learning_plan"] = _jsonable(dict(state.get("learning_plan", {})))
    projection["resource_specs"] = _jsonable(list(state.get("resource_specs", []))[:100])
    projection["resource_executions"] = _jsonable(
        list(state.get("resource_executions", []))[:200]
    )
    projection["resource_progress_summary"] = _jsonable(
        dict(state.get("resource_progress_summary", {}))
    )
    projection["evidence_ids"] = [
        item.evidence_id if isinstance(item, EvidenceItem) else str(item.get("evidence_id", ""))
        for item in state.get("retrieved_evidence", [])
    ]
    projection["resource_ids"] = [
        getattr(item, "resource_id", None) or str(item.get("resource_id", ""))
        for item in state.get("generated_resources", [])
    ]
    projection["claim_ids"] = [
        str(item.get("claim_id"))
        for item in state.get("extracted_claims", [])
        if isinstance(item, dict) and item.get("claim_id")
    ][:2000]
    projection["claim_metrics"] = _jsonable(dict(state.get("claim_metrics", {})))
    review = dict(state.get("review_result", {}))
    projection["review"] = {
        key: _jsonable(review.get(key))
        for key in (
            "decision",
            "status",
            "claim_check_status",
            "hallucination_rate",
            "legacy_reviewer_score",
            "claim_hallucination_rate",
            "claim_metric_status",
            "coverage_rate",
            "difficulty_match",
            "revision_count",
            "issues",
            "revision_instructions",
            "review_ids",
        )
        if key in review
    }
    projection["errors"] = [
        {
            key: item.get(key)
            for key in ("code", "category", "message", "retryable", "source", "attempt", "safe_detail")
            if key in item
        }
        for item in state.get("errors", [])
        if isinstance(item, dict)
    ][:100]
    projection["trace_step_ids"] = [
        item.get("step_id")
        for item in state.get("trace", [])
        if isinstance(item, dict) and item.get("step_id")
    ][:1000]
    return projection
