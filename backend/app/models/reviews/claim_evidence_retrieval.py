"""Versioned contracts for the optional Claim evidence retrieval feature.

The feature is deliberately additive: it never rewrites the first-round Claim
audit.  This module owns the frozen policy, the model envelopes, the durable
session/batch/attempt records and the read-only summary DTO.  Nothing here
imports a Service, repository or Agent, so both persistence implementations and
the pure effective-judgement resolver can share it.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional, Sequence

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgeType,
    ClaimJudgementStatus,
    ClaimVerdict,
)


CONTRACT_VERSION = "claim-evidence-retrieval/v1"
QUERY_PROMPT_VERSION = "claim-evidence-query-v1"
REJUDGE_PROMPT_VERSION = "claim-evidence-rejudge-v1"
EXCERPT_STRATEGY = "claim_window_v1"
PREFIX_EXCERPT_STRATEGY = "prefix"
SESSION_ID_PREFIX = "cers_"
SCOPE_ID_PREFIX = "cevs_"
BATCH_ID_PREFIX = "cerb_"
ATTEMPT_ID_PREFIX = "cera_"

MAX_QUERY_CHARS = 512
MAX_CLAIM_QUERIES = 3
MAX_EVIDENCE_CONFLICTS = 8
MAX_BATCH_PAYLOAD_BYTES = 1024 * 1024


class ClaimEvidenceRetrievalStatus(str, Enum):
    NOT_REQUESTED = "not_requested"
    NOT_APPLICABLE = "not_applicable"
    PENDING = "pending"
    QUERYING = "querying"
    RETRIEVING = "retrieving"
    REJUDGING = "rejudging"
    COMPLETED = "completed"
    NO_NEW_EVIDENCE = "no_new_evidence"
    UNAVAILABLE = "unavailable"
    BUDGET_EXHAUSTED = "budget_exhausted"
    BLOCKED = "blocked"
    INTERRUPTED = "interrupted"


TERMINAL_STATUSES = frozenset({
    ClaimEvidenceRetrievalStatus.COMPLETED,
    ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
    ClaimEvidenceRetrievalStatus.UNAVAILABLE,
    ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
    ClaimEvidenceRetrievalStatus.BLOCKED,
    ClaimEvidenceRetrievalStatus.INTERRUPTED,
})
ACTIVE_STATUSES = frozenset({
    ClaimEvidenceRetrievalStatus.PENDING,
    ClaimEvidenceRetrievalStatus.QUERYING,
    ClaimEvidenceRetrievalStatus.RETRIEVING,
    ClaimEvidenceRetrievalStatus.REJUDGING,
})


class ClaimEvidenceBatchKind(str, Enum):
    QUERY = "query"
    RETRIEVE = "retrieve"
    REJUDGE = "rejudge"


class ClaimEvidenceBatchStatus(str, Enum):
    PLANNED = "planned"
    RESERVED = "reserved"
    DISPATCHED = "dispatched"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


class ClaimEvidenceAttemptStatus(str, Enum):
    RESERVED = "reserved"
    # Write-ahead dispatch intent.  It is committed immediately before the
    # transport call: a crash after this point may have consumed provider
    # capacity, so the reservation is never released or resent automatically.
    DISPATCHING = "dispatching"
    SENT = "sent"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    USAGE_UNKNOWN = "usage_unknown"
    # Definitively never dispatched (an upper-layer budget guard refused the
    # call).  Only this state may release the local token reservation.
    NOT_SENT = "not_sent"


CLAIM_EVIDENCE_BATCH_TRANSITIONS: dict[str, frozenset[str]] = {
    ClaimEvidenceBatchStatus.PLANNED.value: frozenset({
        ClaimEvidenceBatchStatus.RESERVED.value,
        # A retrieval batch has no model attempt: it goes straight from planned
        # to completed inside the evidence-append transaction.
        ClaimEvidenceBatchStatus.COMPLETED.value,
        ClaimEvidenceBatchStatus.FAILED.value,
        ClaimEvidenceBatchStatus.INTERRUPTED.value,
    }),
    ClaimEvidenceBatchStatus.RESERVED.value: frozenset({
        ClaimEvidenceBatchStatus.DISPATCHED.value,
        ClaimEvidenceBatchStatus.FAILED.value,
        ClaimEvidenceBatchStatus.INTERRUPTED.value,
    }),
    ClaimEvidenceBatchStatus.DISPATCHED.value: frozenset({
        ClaimEvidenceBatchStatus.COMPLETED.value,
        ClaimEvidenceBatchStatus.FAILED.value,
        ClaimEvidenceBatchStatus.INTERRUPTED.value,
    }),
    ClaimEvidenceBatchStatus.COMPLETED.value: frozenset(),
    ClaimEvidenceBatchStatus.FAILED.value: frozenset(),
    ClaimEvidenceBatchStatus.INTERRUPTED.value: frozenset(),
}


def stable_eid(prefix: str, *parts: object) -> str:
    material = "|".join([CONTRACT_VERSION, *(str(part) for part in parts)])
    return f"{prefix}{hashlib.sha256(material.encode('utf-8')).hexdigest()[:32]}"


def session_id_for(
    *, run_id: str, resource_id: str, resource_version: int,
    review_id: str, content_hash: str, policy_hash: str,
) -> str:
    return stable_eid(
        SESSION_ID_PREFIX, run_id, resource_id, resource_version,
        review_id, content_hash, policy_hash,
    )


def batch_id_for(*, session_id: str, kind: str, ordinal: int, input_hash: str) -> str:
    return stable_eid(BATCH_ID_PREFIX, session_id, kind, ordinal, input_hash)


def attempt_id_for(*, batch_id: str, logical_call_id: str, attempt_no: int) -> str:
    return stable_eid(ATTEMPT_ID_PREFIX, batch_id, logical_call_id, attempt_no)


def scope_id_for(
    *, session_id: str, purpose: str, manifest_hash: str,
) -> str:
    return stable_eid(SCOPE_ID_PREFIX, session_id, purpose, manifest_hash)


def supplement_judgement_id(
    *, claim_id: str, session_id: str, scope_hash: str, prompt_hash: str,
) -> str:
    """Round-1 identity; never reuse the round-0 Claim+Prompt function."""
    return f"jdg_{stable_eid('', claim_id, session_id, scope_hash, prompt_hash)}"


def payload_bytes(payload: Any) -> int:
    import json

    return len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def round_one_identity(supplements: Sequence["ClaimSupplementJudgementV1"]) -> str:
    """Content identity of one complete round-1 judgement set.

    Activation compares this identity inside the write transaction, so a metric
    computed from a stale or partial set can never be committed next to a
    different persisted round-1 result.
    """

    return round_one_identity_from_records([
        {
            "claim_id": item.claim_id,
            "judgement_id": item.judgement_id,
            "status": item.status.value,
            "verdict": item.verdict.value if item.verdict is not None else None,
        }
        for item in supplements
    ])


def round_one_identity_from_records(records: Sequence[dict[str, Any]]) -> str:
    """Canonical identity shared by the DTO, SQL and Memory implementations."""

    from app.models.shared.persistence import canonical_hash

    return canonical_hash({
        "judgements": [
            {
                "claim_id": str(item["claim_id"]),
                "judgement_id": str(item["judgement_id"]),
                "status": str(item["status"]),
                "verdict": None if item.get("verdict") is None else str(item["verdict"]),
            }
            for item in sorted(records, key=lambda value: str(value["claim_id"]))
        ]
    })


class PolicyContractModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid", str_strip_whitespace=True, protected_namespaces=(),
    )


class ClaimEvidenceRetrievalPolicyV1(PolicyContractModel):
    """Frozen engineering limits; every attempt is authorised by this ledger."""

    contract_version: Literal["claim-evidence-retrieval/v1"] = CONTRACT_VERSION
    max_sessions_per_resource_version: int = Field(default=1, ge=1, le=1)
    query_batch_claims: int = Field(default=16, ge=1, le=16)
    rejudge_batch_claims: int = Field(default=16, ge=1, le=16)
    queries_per_claim: int = Field(default=2, ge=1, le=3)
    max_queries_per_claim: int = Field(default=3, ge=1, le=3)
    max_queries: int = Field(default=96, ge=1, le=96)
    queries_per_request: int = Field(default=6, ge=1, le=6)
    max_new_excerpts_per_resource: int = Field(default=8, ge=1, le=8)
    max_new_excerpts: int = Field(default=16, ge=1, le=16)
    max_logical_calls: int = Field(default=16, ge=1, le=16)
    max_attempts: int = Field(default=24, ge=1, le=24)
    attempts_per_call: int = Field(default=3, ge=1, le=3)
    query_input_cap: int = Field(default=16384, ge=1024, le=65536)
    query_output_cap: int = Field(default=4096, ge=512, le=8192)
    rejudge_input_cap: int = Field(default=32768, ge=1024, le=131072)
    rejudge_output_cap: int = Field(default=8192, ge=512, le=16384)
    rejudge_truncated_output_cap: int = Field(default=16384, ge=512, le=32768)
    max_estimated_tokens: int = Field(default=196608, ge=1024)
    attempt_timeout_seconds: float = Field(default=180.0, gt=0, le=180)
    retrieval_timeout_seconds: float = Field(default=120.0, gt=0, le=120)
    max_wall_seconds: float = Field(default=600.0, gt=0, le=600)
    downstream_reserve_seconds: float = Field(default=300.0, ge=0, le=600)
    excerpt_chars: int = Field(default=2000, ge=100, le=4000)
    excerpt_structural_cap: int = Field(default=4000, ge=100, le=10000)
    excerpt_strategy: Literal["claim_window_v1"] = EXCERPT_STRATEGY
    query_prompt_version: str = Field(default=QUERY_PROMPT_VERSION, min_length=1, max_length=64)
    query_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rejudge_prompt_version: str = Field(default=REJUDGE_PROMPT_VERSION, min_length=1, max_length=64)
    rejudge_prompt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    rejudge_schema_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    query_profile: str = Field(default="claim_evidence_query", min_length=1, max_length=64)
    rejudge_profile: str = Field(default="claim_evidence_rejudge", min_length=1, max_length=64)
    model_name: str = Field(default="", max_length=256)
    endpoint_hash: str = Field(default="", max_length=64)
    thinking_mode: str = Field(default="", max_length=32)
    embedding_model: str = Field(default="", max_length=256)
    rerank_model: str = Field(default="", max_length=256)
    gateway_options: dict[str, Any] = Field(default_factory=dict)
    estimator_parameters: dict[str, Any] = Field(default_factory=dict)
    knowledge_base_id: str = Field(default="", max_length=128)
    retrieval_config_hash: str = Field(default="", max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_limits(self) -> "ClaimEvidenceRetrievalPolicyV1":
        if self.queries_per_claim > self.max_queries_per_claim:
            raise ValueError("queries_per_claim cannot exceed max_queries_per_claim")
        if self.rejudge_output_cap > self.rejudge_truncated_output_cap:
            raise ValueError("truncated cap must not lower the normal cap")
        if self.downstream_reserve_seconds >= self.max_wall_seconds:
            raise ValueError("downstream reserve must be shorter than the wall budget")
        if self.excerpt_chars > self.excerpt_structural_cap:
            raise ValueError("excerpt_chars cannot exceed the structural cap")
        return self

    @property
    def policy_hash(self) -> str:
        """Content identity excludes the freeze timestamp.

        Two submissions of the same frozen contract must share one budget
        ledger; only values that change behaviour participate in the hash.
        """

        from app.models.shared.persistence import canonical_hash

        return canonical_hash(self.model_dump(mode="json", exclude={"created_at"}))


class ClaimEvidenceRetrievalSnapshotV1(PolicyContractModel):
    """Frozen workflow snapshot; absence of this object means "closed"."""

    enabled: bool
    policy: ClaimEvidenceRetrievalPolicyV1
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    claim_extraction_mode: Optional[str] = Field(default=None, max_length=32)
    claim_extraction_policy_hash: Optional[str] = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def validate_hash(self) -> "ClaimEvidenceRetrievalSnapshotV1":
        if not self.enabled:
            raise ValueError("disabled snapshot must not be frozen")
        if self.policy.policy_hash != self.policy_hash:
            raise ValueError("frozen policy hash mismatch")
        return self


class ClaimQueryText(PolicyContractModel):
    text: str = Field(min_length=1, max_length=MAX_QUERY_CHARS)


class ClaimQueryItem(PolicyContractModel):
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    queries: list[ClaimQueryText] = Field(min_length=1, max_length=MAX_CLAIM_QUERIES)


class ClaimQueryBatchOutputV1(PolicyContractModel):
    """Model envelope for batched query construction; no URLs or IDs allowed."""

    batch_id: str = Field(min_length=1, max_length=128)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    items: list[ClaimQueryItem] = Field(min_length=1, max_length=16)

    @field_validator("items")
    @classmethod
    def unique_claims(cls, values: list[ClaimQueryItem]) -> list[ClaimQueryItem]:
        ids = [item.claim_id for item in values]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate claim_id in query batch")
        return values


class ClaimSupplementJudgementCandidate(PolicyContractModel):
    """Round-1 Judge envelope; ``evidence_conflict`` is private, not a verdict."""

    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    verdict: ClaimVerdict
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    reason: str = Field(min_length=1, max_length=4000)
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_conflict: bool = False
    conflicting_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_CONFLICTS)

    @model_validator(mode="after")
    def validate_conflict(self) -> "ClaimSupplementJudgementCandidate":
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("evidence_ids must be unique")
        if len(self.conflicting_evidence_ids) != len(set(self.conflicting_evidence_ids)):
            raise ValueError("conflicting_evidence_ids must be unique")
        if not self.evidence_conflict and self.conflicting_evidence_ids:
            raise ValueError("conflict ids require evidence_conflict=true")
        if self.evidence_conflict and not self.conflicting_evidence_ids:
            raise ValueError("evidence_conflict requires conflicting evidence ids")
        if not self.evidence_conflict and self.verdict == ClaimVerdict.CONTRADICTED:
            # A plain contradiction still blocks publication; it simply is not
            # a source conflict between two applicable passages.
            return self
        return self


class ClaimSupplementJudgementLLMOutput(PolicyContractModel):
    judgements: list[ClaimSupplementJudgementCandidate] = Field(
        default_factory=list, max_length=16,
    )


class ClaimEvidenceRetrievalSessionV1(PolicyContractModel):
    session_id: str = Field(pattern=r"^cers_[0-9a-f]{32}$")
    run_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1, max_length=128)
    content_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_evidence_set_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    initial_judgement_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_claim_ids: list[str] = Field(default_factory=list, max_length=128)
    query_count: int = Field(default=0, ge=0)
    evidence_scope_ids: list[str] = Field(default_factory=list, max_length=8)
    status: ClaimEvidenceRetrievalStatus = ClaimEvidenceRetrievalStatus.PENDING
    reason_code: Optional[str] = Field(default=None, max_length=64)
    active: bool = False
    hard_block: bool = False
    hard_block_reason: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None

    @model_validator(mode="after")
    def validate_terminal(self) -> "ClaimEvidenceRetrievalSessionV1":
        if self.active and self.status != ClaimEvidenceRetrievalStatus.COMPLETED:
            raise ValueError("only a completed session can be activated")
        if self.status in TERMINAL_STATUSES and self.completed_at is None:
            raise ValueError("terminal session requires completed_at")
        if self.status not in TERMINAL_STATUSES and self.completed_at is not None:
            raise ValueError("non-terminal session forbids completed_at")
        if len(self.target_claim_ids) != len(set(self.target_claim_ids)):
            raise ValueError("target_claim_ids must be unique")
        return self


class ClaimEvidenceRetrievalBatchV1(PolicyContractModel):
    batch_id: str = Field(pattern=r"^cerb_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^cers_[0-9a-f]{32}$")
    kind: ClaimEvidenceBatchKind
    ordinal: int = Field(ge=0)
    input_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_hash: Optional[str] = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    status: ClaimEvidenceBatchStatus = ClaimEvidenceBatchStatus.PLANNED
    payload: dict[str, Any] = Field(default_factory=dict)
    expected_claim_ids: list[str] = Field(default_factory=list, max_length=16)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_payload(self) -> "ClaimEvidenceRetrievalBatchV1":
        if payload_bytes(self.payload) > MAX_BATCH_PAYLOAD_BYTES:
            raise ValueError("batch payload exceeds the 1 MiB checkpoint bound")
        if self.status == ClaimEvidenceBatchStatus.COMPLETED and self.output_hash is None:
            raise ValueError("completed batch requires an output hash")
        return self


class ClaimEvidenceRetrievalAttemptV1(PolicyContractModel):
    attempt_id: str = Field(pattern=r"^cera_[0-9a-f]{32}$")
    batch_id: str = Field(pattern=r"^cerb_[0-9a-f]{32}$")
    logical_call_id: str = Field(min_length=1, max_length=128)
    attempt_no: int = Field(ge=1, le=3)
    owner: str = Field(min_length=1, max_length=256)
    epoch: int = Field(ge=0)
    reserved_tokens: int = Field(ge=0)
    output_cap: int = Field(ge=1)
    known_tokens: Optional[int] = Field(default=None, ge=0)
    status: ClaimEvidenceAttemptStatus = ClaimEvidenceAttemptStatus.RESERVED
    unknown_usage: bool = False
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: Optional[datetime] = None


class ClaimReviewEvidenceSetV1(PolicyContractModel):
    scope_id: str = Field(pattern=r"^cevs_[0-9a-f]{32}$")
    run_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1, max_length=128)
    purpose: Literal["audit", "generation"]
    session_id: Optional[str] = Field(default=None, max_length=64)
    base_evidence_ids: list[str] = Field(default_factory=list, max_length=64)
    added_evidence_ids: list[str] = Field(default_factory=list, max_length=16)
    snapshot_hashes: dict[str, str] = Field(default_factory=dict)
    manifest: list[dict[str, Any]] = Field(default_factory=list, max_length=80)
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_scope_id: Optional[str] = Field(default=None, max_length=64)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_manifest(self) -> "ClaimReviewEvidenceSetV1":
        from app.models.shared.persistence import canonical_hash

        if canonical_hash(self.manifest_payload()) != self.manifest_hash:
            raise ValueError("evidence manifest hash mismatch")
        if len(self.added_evidence_ids) != len(set(self.added_evidence_ids)):
            raise ValueError("added evidence ids must be unique")
        if set(self.added_evidence_ids) - set(self.snapshot_hashes):
            raise ValueError("every added evidence id requires a snapshot hash")
        if payload_bytes(self.manifest) > MAX_BATCH_PAYLOAD_BYTES:
            raise ValueError("evidence manifest exceeds the 1 MiB bound")
        return self

    def manifest_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "resource_id": self.resource_id,
            "resource_version": self.resource_version,
            "review_id": self.review_id,
            "purpose": self.purpose,
            "session_id": self.session_id,
            "base_evidence_ids": list(self.base_evidence_ids),
            "added_evidence_ids": list(self.added_evidence_ids),
            "parent_scope_id": self.parent_scope_id,
            "manifest": self.manifest,
        }


def build_evidence_set(
    *,
    run_id: str,
    resource_id: str,
    resource_version: int,
    review_id: str,
    purpose: Literal["audit", "generation"],
    session_id: str | None,
    base_evidence_ids: Sequence[str],
    added_evidence_ids: Sequence[str],
    snapshot_hashes: dict[str, str],
    manifest: list[dict[str, Any]],
    parent_scope_id: str | None = None,
    created_at: datetime | None = None,
) -> ClaimReviewEvidenceSetV1:
    """Construct a scope whose manifest hash is computed from its own payload."""

    from app.models.shared.persistence import canonical_hash

    scope_id = scope_id_for(
        session_id=session_id or "", purpose=purpose,
        manifest_hash=canonical_hash({"placeholder": manifest}),
    )
    payload = {
        "run_id": run_id,
        "resource_id": resource_id,
        "resource_version": resource_version,
        "review_id": review_id,
        "purpose": purpose,
        "session_id": session_id,
        "base_evidence_ids": list(base_evidence_ids),
        "added_evidence_ids": list(added_evidence_ids),
        "parent_scope_id": parent_scope_id,
        "manifest": manifest,
    }
    manifest_hash = canonical_hash(payload)
    return ClaimReviewEvidenceSetV1(
        scope_id=scope_id_for(
            session_id=session_id or "", purpose=purpose, manifest_hash=manifest_hash,
        ),
        run_id=run_id,
        resource_id=resource_id,
        resource_version=resource_version,
        review_id=review_id,
        purpose=purpose,
        session_id=session_id,
        base_evidence_ids=list(base_evidence_ids),
        added_evidence_ids=list(added_evidence_ids),
        snapshot_hashes=dict(snapshot_hashes),
        manifest=manifest,
        manifest_hash=manifest_hash,
        parent_scope_id=parent_scope_id,
        created_at=created_at or datetime.now(timezone.utc),
    )


class ClaimSupplementJudgementV1(PolicyContractModel):
    judgement_id: str = Field(pattern=r"^jdg_[0-9a-f]{32}$")
    session_id: str = Field(pattern=r"^cers_[0-9a-f]{32}$")
    claim_id: str = Field(pattern=r"^clm_[0-9a-f]{32}$")
    run_id: str = Field(min_length=1, max_length=128)
    resource_id: str = Field(min_length=1, max_length=64)
    resource_version: int = Field(ge=1)
    review_id: str = Field(min_length=1, max_length=128)
    round_no: Literal[1] = 1
    scope_id: str = Field(min_length=1, max_length=64)
    status: ClaimJudgementStatus
    verdict: Optional[ClaimVerdict] = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=50)
    conflicting_evidence_ids: list[str] = Field(default_factory=list, max_length=MAX_EVIDENCE_CONFLICTS)
    evidence_conflict: bool = False
    reason: str = Field(min_length=1, max_length=4000)
    judge_model: Optional[str] = Field(default=None, max_length=256)
    judge_prompt_version: str = Field(min_length=1, max_length=64)
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @model_validator(mode="after")
    def validate_completed(self) -> "ClaimSupplementJudgementV1":
        if self.status is ClaimJudgementStatus.COMPLETED and self.verdict is None:
            raise ValueError("completed supplement requires a verdict")
        if self.status is not ClaimJudgementStatus.COMPLETED and self.verdict is not None:
            raise ValueError("non-completed supplement forbids a verdict")
        if self.evidence_conflict and not self.conflicting_evidence_ids:
            raise ValueError("conflict requires conflicting evidence ids")
        return self

    def as_judgement(self) -> ClaimJudgement:
        return ClaimJudgement(
            judgement_id=self.judgement_id,
            claim_id=self.claim_id,
            run_id=self.run_id,
            resource_id=self.resource_id,
            resource_version=self.resource_version,
            review_id=self.review_id,
            status=self.status,
            verdict=self.verdict,
            evidence_ids=list(self.evidence_ids),
            reason=self.reason,
            judge_type=ClaimJudgeType.LLM,
            judge_model=self.judge_model,
            judge_prompt_version=self.judge_prompt_version,
            confidence=self.confidence,
            created_at=self.created_at,
        )


class ClaimEvidenceSessionSummaryV1(PolicyContractModel):
    session_id: str
    resource_version: int
    status: ClaimEvidenceRetrievalStatus
    reason_code: Optional[str] = None
    active: bool = False
    hard_block: bool = False
    target_claim_total: int = Field(default=0, ge=0)
    attempted_claim_total: int = Field(default=0, ge=0)
    remaining_claim_total: int = Field(default=0, ge=0)
    query_total: int = Field(default=0, ge=0)
    logical_call_total: int = Field(default=0, ge=0)
    attempt_total: int = Field(default=0, ge=0)
    known_tokens: int = Field(default=0, ge=0)
    unknown_tokens: int = Field(default=0, ge=0)
    evidence_scope_ids: list[str] = Field(default_factory=list)


class ClaimEvidenceRetrievalSummaryV1(PolicyContractModel):
    """Versioned read-only projection; never carries prompts or private context."""

    contract_version: Literal["claim-evidence-retrieval/v1"] = CONTRACT_VERSION
    run_id: str
    requested: bool
    status: ClaimEvidenceRetrievalStatus
    reason_code: Optional[str] = None
    resource_id: Optional[str] = None
    resource_version: Optional[int] = None
    review_id: Optional[str] = None
    target_claim_total: int = Field(default=0, ge=0)
    attempted_claim_total: int = Field(default=0, ge=0)
    remaining_claim_total: int = Field(default=0, ge=0)
    query_total: int = Field(default=0, ge=0)
    logical_call_total: int = Field(default=0, ge=0)
    attempt_total: int = Field(default=0, ge=0)
    known_tokens: int = Field(default=0, ge=0)
    unknown_tokens: int = Field(default=0, ge=0)
    initial_supported_total: int = Field(default=0, ge=0)
    initial_contradicted_total: int = Field(default=0, ge=0)
    initial_not_in_evidence_total: int = Field(default=0, ge=0)
    effective_supported_total: int = Field(default=0, ge=0)
    effective_contradicted_total: int = Field(default=0, ge=0)
    effective_not_in_evidence_total: int = Field(default=0, ge=0)
    factual_claim_total: int = Field(default=0, ge=0)
    evidence_scope_ids: list[str] = Field(default_factory=list)
    sessions: list[ClaimEvidenceSessionSummaryV1] = Field(default_factory=list)


def validate_feature_switch(
    *,
    include_claim_evidence_retrieval: bool,
    include_claim_check: bool,
    include_review: bool,
) -> None:
    """Reject invalid combinations with the existing 422 validation shape."""

    if not include_claim_evidence_retrieval:
        return
    if not include_claim_check:
        raise ValueError(
            "include_claim_evidence_retrieval requires include_claim_check=true"
        )
    if not include_review:
        raise ValueError(
            "include_claim_evidence_retrieval requires include_review=true"
        )


def normalize_inherited_switch(
    *,
    requested: Optional[bool],
    inherited: bool,
    inherited_claim_check: bool,
    effective_claim_check: bool,
) -> bool:
    """Resolve the tri-state continuation flag without widening Claim audit."""

    if requested is None:
        value = inherited and inherited_claim_check
    else:
        value = bool(requested)
    if not effective_claim_check:
        return False
    return bool(value)


__all__ = [
    "ACTIVE_STATUSES",
    "CLAIM_EVIDENCE_BATCH_TRANSITIONS",
    "CONTRACT_VERSION",
    "ClaimEvidenceAttemptStatus",
    "ClaimEvidenceBatchKind",
    "ClaimEvidenceBatchStatus",
    "ClaimEvidenceRetrievalAttemptV1",
    "ClaimEvidenceRetrievalBatchV1",
    "ClaimEvidenceRetrievalPolicyV1",
    "ClaimEvidenceRetrievalSessionV1",
    "ClaimEvidenceRetrievalSnapshotV1",
    "ClaimEvidenceRetrievalStatus",
    "ClaimEvidenceRetrievalSummaryV1",
    "ClaimEvidenceSessionSummaryV1",
    "ClaimQueryBatchOutputV1",
    "ClaimQueryItem",
    "ClaimQueryText",
    "ClaimReviewEvidenceSetV1",
    "ClaimSupplementJudgementCandidate",
    "ClaimSupplementJudgementLLMOutput",
    "ClaimSupplementJudgementV1",
    "EXCERPT_STRATEGY",
    "MAX_BATCH_PAYLOAD_BYTES",
    "PREFIX_EXCERPT_STRATEGY",
    "QUERY_PROMPT_VERSION",
    "REJUDGE_PROMPT_VERSION",
    "TERMINAL_STATUSES",
    "attempt_id_for",
    "batch_id_for",
    "build_evidence_set",
    "scope_id_for",
    "normalize_inherited_switch",
    "payload_bytes",
    "round_one_identity",
    "round_one_identity_from_records",
    "session_id_for",
    "supplement_judgement_id",
    "validate_feature_switch",
]
