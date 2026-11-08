"""V1 contracts for the bypass LLM-call accounting observation layer.

These DTOs are shared by the in-memory collector, the independent accounting
store and the read-only query API.  The module intentionally depends only on
the standard library and Pydantic so ``models`` never imports persistence,
services or agent code.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field


LLM_ACCOUNTING_SCHEMA_VERSION = "llm-accounting-v1"

# Frozen capacity guards (T41 §4.5).  Reaching a guard stops appending
# observations only; the business keeps running untouched.
MAX_CALLS_PER_SEGMENT = 8192
MAX_ATTEMPTS_PER_CALL = 3
MAX_ATTRIBUTE_SCOPES_PER_CALL = 512
MAX_SEGMENT_JSON_BYTES = 8 * 1024 * 1024
MAX_BATCH_SEGMENTS = 128
MAX_BATCH_CALLS = 8192
MAX_BATCH_ATTRIBUTE_SCOPES = 512
MAX_BATCH_JSON_BYTES = 8 * 1024 * 1024

# Bounded identity/string lengths captured at collection time.
MAX_IDENTITY_CHARS = 128
MAX_LONG_IDENTITY_CHARS = 256
MAX_MODEL_CHARS = 128
MAX_REASON_CHARS = 64
MAX_RESOURCE_LABELS = 128


class AccountingDomain(str, Enum):
    LEARNING_DOCUMENTS = "learning_documents"
    COURSEWARE = "courseware"


Attribution = Literal["task", "resource", "resource_set", "unknown"]


class LLMAttemptEvidenceV1(BaseModel):
    """One gateway attempt as observed from summary and/or transport helper."""

    model_config = ConfigDict(protected_namespaces=())

    ordinal: int = Field(ge=1)
    gateway_status: str | None = None
    error_code: str | None = None
    error_category: str | None = None
    latency_ms: int | None = None
    structured_output_mode: str | None = None
    usage_input_tokens: int | None = Field(default=None, ge=0)
    usage_output_tokens: int | None = Field(default=None, ge=0)
    usage_total_tokens: int | None = Field(default=None, ge=0)
    usage_source: Literal["summary", "raw", "both", "none", "conflict"] = "none"
    provider_request_id: str | None = None
    # Transport-helper evidence for the same ordinal; never added to summary.
    helper_observed: bool = False
    helper_error_class: str | None = None
    helper_raw_success: bool = False
    helper_usage_input_tokens: int | None = Field(default=None, ge=0)
    helper_usage_output_tokens: int | None = Field(default=None, ge=0)
    helper_usage_total_tokens: int | None = Field(default=None, ge=0)
    helper_provider_request_id: str | None = None
    helper_finish_reason: str | None = None

    def merged_usage(self) -> tuple[int | None, int | None, int | None, bool]:
        """Merge summary and helper usage per T41 §4.4 field by field.

        Summary values win when known; raw helper values fill gaps; a real
        disagreement marks the attempt conflicted (all fields unknown).
        """

        conflict = False
        values: list[int | None] = []
        for summary_value, helper_value in (
            (self.usage_input_tokens, self.helper_usage_input_tokens),
            (self.usage_output_tokens, self.helper_usage_output_tokens),
            (self.usage_total_tokens, self.helper_usage_total_tokens),
        ):
            if summary_value is not None and helper_value is not None and summary_value != helper_value:
                conflict = True
                values.append(None)
            elif summary_value is not None:
                values.append(summary_value)
            else:
                values.append(helper_value)
        return (values[0], values[1], values[2], conflict)


class LLMCallObservationV1(BaseModel):
    """One logical call into the real LLMGateway public entry point."""

    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = LLM_ACCOUNTING_SCHEMA_VERSION
    domain: str
    run_id: str = Field(min_length=1, max_length=MAX_LONG_IDENTITY_CHARS)
    segment_id: str = Field(min_length=1, max_length=MAX_LONG_IDENTITY_CHARS)
    observation_id: int = Field(ge=1)
    source_call_id: str | None = None
    stage: str | None = None
    step_id: str | None = None
    stage_sequence: int | None = None
    node_name: str | None = None
    schema_name: str | None = None
    model_name: str | None = None
    structured_output_mode: str | None = None
    attribution: Attribution = "unknown"
    resource_labels: list[str] = Field(default_factory=list, max_length=MAX_RESOURCE_LABELS)
    attempts: list[LLMAttemptEvidenceV1] = Field(default_factory=list)
    observed_attempt_count: int = Field(default=0, ge=0)
    gateway_attempt_count: int | None = None
    gateway_retry_count: int | None = None
    outcome: Literal["success", "gateway_error", "exception"] = "success"
    error_code: str | None = None
    error_class: str | None = None
    # Complete per-field usage requires every attempt known and consistent
    # with the gateway's own top-level usage.
    usage_input_tokens: int | None = Field(default=None, ge=0)
    usage_output_tokens: int | None = Field(default=None, ge=0)
    usage_total_tokens: int | None = Field(default=None, ge=0)
    known_input_tokens: int = Field(default=0, ge=0)
    known_output_tokens: int = Field(default=0, ge=0)
    known_total_tokens: int = Field(default=0, ge=0)
    usage_complete: bool = False
    usage_mismatch: bool = False
    known_llm_duration_ms: int = Field(default=0, ge=0)
    capture_complete: bool = True
    attempt_complete: bool = True
    attribution_complete: bool = True
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def observation_key(self) -> tuple[str, str, str, int]:
        return (self.domain, self.run_id, self.segment_id, self.observation_id)

    def stable_payload(self) -> dict[str, Any]:
        """Canonical projection excluding unstable fields for hashing."""

        data = self.model_dump(mode="json", exclude_none=False)
        data.pop("recorded_at", None)
        return data


class AccountingSegmentV1(BaseModel):
    """One observed execution segment and its frozen call list."""

    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = LLM_ACCOUNTING_SCHEMA_VERSION
    domain: str
    run_id: str
    segment_id: str
    process_nonce: str
    stage: str | None = None
    calls: list[LLMCallObservationV1] = Field(default_factory=list)
    call_count: int = Field(default=0, ge=0)
    sealed: bool = False
    capacity_exceeded: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)
    recorded_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def stable_payload(self) -> dict[str, Any]:
        data = self.model_dump(mode="json", exclude={"calls", "recorded_at"})
        data["calls"] = [call.stable_payload() for call in self.calls]
        return data

    def payload_hash(self) -> str:
        return canonical_accounting_hash(self.stable_payload())


class SegmentSubmissionV1(BaseModel):
    """Immutable snapshot handed from the collector to the publisher."""

    segment: AccountingSegmentV1
    payload_hash: str


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_accounting_hash(payload: Any) -> str:
    return hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()


class LLMUsageSummaryV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    observed_calls: int = Field(default=0, ge=0)
    known_input_tokens: int = Field(default=0, ge=0)
    known_output_tokens: int = Field(default=0, ge=0)
    known_total_tokens: int = Field(default=0, ge=0)
    complete_input_tokens: int | None = None
    complete_output_tokens: int | None = None
    complete_total_tokens: int | None = None
    usage_complete_calls: int = Field(default=0, ge=0)
    known_llm_duration_ms: int = Field(default=0, ge=0)


class StageSummaryV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    stage: str
    usage: LLMUsageSummaryV1 = Field(default_factory=LLMUsageSummaryV1)


class ResourcePartitionSummaryV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    partition: Literal["exclusive", "shared", "unallocated"]
    label: str
    usage: LLMUsageSummaryV1 = Field(default_factory=LLMUsageSummaryV1)


class SegmentInfoV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    segment_id: str
    recorded_at: str
    call_count: int = Field(default=0, ge=0)
    sealed: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)
    capacity_exceeded: bool = False


class TaskLLMAccountingResponseV1(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    schema_version: str = LLM_ACCOUNTING_SCHEMA_VERSION
    domain: str
    run_id: str
    scope: Literal["full_generation_workflow"] = "full_generation_workflow"
    availability: Literal["available", "partial", "pending", "not_recorded", "unavailable"]
    capture_complete: bool = False
    attempt_complete: bool = False
    usage_complete: bool = False
    attribution_complete: bool = False
    coverage_complete: bool = False
    as_of: str | None = None
    task_summary: LLMUsageSummaryV1 = Field(default_factory=LLMUsageSummaryV1)
    stage_summaries: list[StageSummaryV1] = Field(default_factory=list)
    resource_partition_summaries: list[ResourcePartitionSummaryV1] = Field(default_factory=list)
    segments: list[SegmentInfoV1] = Field(default_factory=list)
    calls: list[LLMCallObservationV1] = Field(default_factory=list)
    include_calls: bool = False
    stage_filter: str | None = None
    filtered_summary: LLMUsageSummaryV1 | None = None
    next_cursor: str | None = None
    has_more: bool = False
    incomplete_reasons: list[str] = Field(default_factory=list)


def summarize_observations(observations: Iterable[LLMCallObservationV1]) -> LLMUsageSummaryV1:
    calls = list(observations)
    summary = LLMUsageSummaryV1(
        observed_calls=len(calls),
        usage_complete_calls=sum(c.usage_complete for c in calls),
        known_llm_duration_ms=sum(c.known_llm_duration_ms for c in calls),
    )
    for field in ("input", "output", "total"):
        setattr(summary, "known_" + field + "_tokens", sum(getattr(c, "known_" + field + "_tokens") for c in calls))
        values = [getattr(c, "usage_" + field + "_tokens") for c in calls]
        complete = bool(calls) and all(c.capture_complete and c.attempt_complete for c in calls) and all(v is not None for v in values)
        setattr(summary, "complete_" + field + "_tokens", sum(values) if complete else None)
    return summary


def deduplicate_observations(
    observations: Iterable[LLMCallObservationV1],
) -> tuple[list[LLMCallObservationV1], int]:
    """Deduplicate by observation primary key + content hash (T41 §4.1).

    The same primary key replayed with identical content is a no-op; a
    different content hash under the same primary key is a conflict and the
    first value wins (never overwritten).
    """

    by_key: dict[tuple[str, str, str, int], LLMCallObservationV1] = {}
    seen_hashes: dict[tuple[str, str, str, int], str] = {}
    conflicts = 0
    for observation in observations:
        key = observation.observation_key()
        payload_hash = canonical_accounting_hash(observation.stable_payload())
        existing_hash = seen_hashes.get(key)
        if existing_hash is None:
            by_key[key] = observation
            seen_hashes[key] = payload_hash
        elif existing_hash != payload_hash:
            conflicts += 1
    return list(by_key.values()), conflicts


def stage_sort_key(observation: LLMCallObservationV1) -> tuple[Any, ...]:
    return (
        observation.domain,
        observation.run_id,
        observation.stage_sequence if observation.stage_sequence is not None else 1 << 30,
        observation.stage or "",
        observation.segment_id,
        observation.observation_id,
    )


def build_task_response(
    *,
    domain: str,
    run_id: str,
    observations: list[LLMCallObservationV1],
    segments: list[SegmentInfoV1],
    availability: str,
    coverage_complete: bool,
    incomplete_reasons: list[str] | None = None,
    include_calls: bool = False,
    stage_filter: str | None = None,
    next_cursor: str | None = None,
    has_more: bool = False,
    as_of: str | None = None,
    conflicts: int = 0,
) -> TaskLLMAccountingResponseV1:
    """Aggregate one task's deduplicated observation set into a response."""

    ordered = sorted(observations, key=stage_sort_key)
    reasons = list(dict.fromkeys(incomplete_reasons or []))
    if conflicts:
        reasons.append("payload_conflict")
    capture_complete = all(call.capture_complete for call in ordered) and bool(ordered)
    attempt_complete = all(call.attempt_complete for call in ordered) and bool(ordered)
    usage_complete = all(call.usage_complete for call in ordered) and bool(ordered)
    attribution_complete = all(call.attribution_complete for call in ordered) and bool(ordered)

    stage_map: dict[str, list[LLMCallObservationV1]] = {}
    for observation in ordered:
        stage_map.setdefault(observation.stage or "unknown", []).append(observation)
    stage_summaries = [
        StageSummaryV1(stage=stage, usage=summarize_observations(calls))
        for stage, calls in sorted(stage_map.items())
    ]

    partitions: dict[tuple[str, str], list[LLMCallObservationV1]] = {}
    for observation in ordered:
        if observation.attribution == "resource" and observation.resource_labels:
            # The first label owns an exclusive call. Remaining labels are
            # descriptive tags (type/batch/review), not additive resources.
            partitions.setdefault(("exclusive", observation.resource_labels[0]), []).append(observation)
        elif observation.attribution == "resource_set":
            label = "shared:" + json.dumps(sorted(set(observation.resource_labels)), ensure_ascii=False)
            partitions.setdefault(("shared", label), []).append(observation)
        else:
            partitions.setdefault(("unallocated", "task"), []).append(observation)
    resource_partition_summaries = [
        ResourcePartitionSummaryV1(partition=kind, label=label, usage=summarize_observations(calls))
        for (kind, label), calls in sorted(partitions.items())
    ]

    filtered_summary = None
    if stage_filter is not None:
        filtered_summary = summarize_observations(
            [call for call in ordered if call.stage == stage_filter]
        )

    response = TaskLLMAccountingResponseV1(
        domain=domain,
        run_id=run_id,
        availability=availability,  # type: ignore[arg-type]
        capture_complete=capture_complete and not reasons,
        attempt_complete=attempt_complete and not reasons,
        usage_complete=usage_complete and not reasons,
        attribution_complete=attribution_complete and not reasons,
        coverage_complete=coverage_complete,
        as_of=as_of,
        task_summary=summarize_observations(ordered),
        stage_summaries=stage_summaries,
        resource_partition_summaries=resource_partition_summaries,
        segments=segments,
        calls=(
            [call for call in ordered if stage_filter is None or call.stage == stage_filter]
            if include_calls
            else []
        ),
        include_calls=include_calls,
        stage_filter=stage_filter,
        filtered_summary=filtered_summary,
        next_cursor=next_cursor,
        has_more=has_more,
        incomplete_reasons=reasons,
    )
    return response
