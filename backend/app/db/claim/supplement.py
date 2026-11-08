"""Durable ledger, session and round-1 storage for Claim evidence retrieval.

Both implementations expose the same semantics:

* the run row is the single budget authorisation ledger (CAS on revision);
* a session is unique per ``(run, resource, version, review)`` and terminal rows
  never change status again;
* retrieval batches persist the new snapshots and the batch completion in one
  transaction;
* a round-1 judgement batch persists its rows, evidence bindings and the
  irreversible ``hard_block`` flag in one transaction;
* activation is one transaction that flips ``active`` and rewrites the review
  summary to the effective metric.

No model or retrieval call is made while a transaction or lock is held.
"""

from __future__ import annotations

import copy
import hashlib
import threading
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.db.audit.base import PersistenceConflict
from app.db.claim.supplement_models import (
    ClaimEvidenceRetrievalAttemptORM,
    ClaimEvidenceRetrievalBatchORM,
    ClaimEvidenceRetrievalRunORM,
    ClaimEvidenceRetrievalSessionORM,
    ClaimReviewEvidenceSetORM,
    ClaimSupplementEvidenceORM,
    ClaimSupplementJudgementORM,
)
from app.models.reviews.claim_evidence_retrieval import (
    CLAIM_EVIDENCE_BATCH_TRANSITIONS,
    TERMINAL_STATUSES,
    ClaimEvidenceAttemptStatus,
    ClaimEvidenceBatchKind,
    ClaimEvidenceBatchStatus,
    ClaimEvidenceRetrievalAttemptV1,
    ClaimEvidenceRetrievalBatchV1,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimReviewEvidenceSetV1,
    ClaimSupplementJudgementV1,
    payload_bytes,
    round_one_identity_from_records,
)
from app.models.reviews.claims import ClaimJudgementStatus
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash


class SupplementBudgetExceeded(PersistenceConflict):
    """The frozen ledger cannot authorise one more attempt."""


class SupplementSessionClosed(PersistenceConflict):
    """A terminal session may not re-open or change status."""


def utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass(frozen=True)
class SupplementRunLedger:
    run_id: str
    policy_hash: str
    policy: ClaimEvidenceRetrievalPolicyV1
    revision: int
    reserved_tokens: int
    known_tokens: int
    unknown_tokens: int
    logical_calls: int
    attempts: int
    query_count: int
    owner: str | None
    epoch: int
    started_at: datetime
    deadline_at: datetime
    status: str

    @property
    def settled_tokens(self) -> int:
        return self.known_tokens + self.unknown_tokens

    @property
    def charged_tokens(self) -> int:
        return self.reserved_tokens + self.settled_tokens


def _snapshot_rows(evidence: Sequence[PersistedEvidenceSnapshot]) -> list[dict[str, Any]]:
    rows = []
    for item in evidence:
        payload = item.model_dump(mode="python")
        payload["locator"] = item.locator.model_dump(mode="json")
        rows.append(payload)
    return rows


def _validate_append(
    *,
    run_id: str,
    step_id: str,
    knowledge_base_id: str | None,
    evidence: Sequence[PersistedEvidenceSnapshot],
) -> None:
    seen: set[str] = set()
    for item in evidence:
        if item.evidence_id in seen:
            raise PersistenceConflict("duplicate evidence id in one append")
        seen.add(item.evidence_id)
        if item.run_id != run_id:
            raise PersistenceConflict("evidence crosses run boundary")
        if item.retrieval_step_id != step_id:
            raise PersistenceConflict("evidence crosses step boundary")
        if knowledge_base_id and item.knowledge_base_id != knowledge_base_id:
            raise PersistenceConflict("evidence is outside the run knowledge base")


class BaseClaimSupplementRepository(ABC):
    """Shared contract; callers never issue SQL or touch ORM objects."""

    def __init__(self, *, claim_repository, audit_repository) -> None:
        self.claim_repository = claim_repository
        self.audit_repository = audit_repository

    # ---- run ledger -------------------------------------------------
    @abstractmethod
    def get_run(self, run_id: str) -> SupplementRunLedger | None: ...

    @abstractmethod
    def open_run(
        self,
        *,
        run_id: str,
        policy: ClaimEvidenceRetrievalPolicyV1,
        started_at: datetime,
        deadline_at: datetime,
        owner: str | None = None,
        epoch: int = 0,
    ) -> SupplementRunLedger: ...

    @abstractmethod
    def reserve_attempt(
        self,
        *,
        run_id: str,
        owner: str,
        epoch: int,
        reserved_tokens: int,
        attempt_id: str,
        batch_id: str,
        logical_call_id: str,
        attempt_no: int,
        output_cap: int,
        now: datetime,
    ) -> SupplementRunLedger: ...

    @abstractmethod
    def mark_dispatched(
        self, *, run_id: str, attempt_id: str, owner: str, epoch: int, now: datetime,
    ) -> SupplementRunLedger:
        """Persist the dispatch intent before the transport call."""

    @abstractmethod
    def settle_attempt(
        self,
        *,
        run_id: str,
        attempt_id: str,
        owner: str,
        epoch: int,
        status: ClaimEvidenceAttemptStatus,
        known_tokens: int | None,
        now: datetime,
    ) -> SupplementRunLedger: ...

    @abstractmethod
    def list_attempts(self, run_id: str) -> list[ClaimEvidenceRetrievalAttemptV1]:
        """Read the persisted attempt lifecycle for recovery and audit."""

    @abstractmethod
    def interrupt_runs(
        self, run_ids: Sequence[str], *, now: datetime, reason_code: str = "run_interrupted",
    ) -> int:
        """Mark every in-flight session of interrupted runs, without resending.

        In-flight reservations are reconciled with the same rule as a live
        settlement: a pre-dispatch reservation is released, a dispatch intent
        keeps its reserve charged as unknown usage.
        """

    @abstractmethod
    def count_logical_call(
        self, *, run_id: str, owner: str, epoch: int, now: datetime,
    ) -> SupplementRunLedger: ...

    @abstractmethod
    def record_query_count(self, *, run_id: str, count: int) -> SupplementRunLedger: ...

    @abstractmethod
    def touch_run(self, *, run_id: str, status: str, owner: str, epoch: int) -> None: ...

    # ---- sessions ---------------------------------------------------
    @abstractmethod
    def get_session(self, session_id: str) -> ClaimEvidenceRetrievalSessionV1 | None: ...

    @abstractmethod
    def find_session(
        self, *, run_id: str, resource_id: str, resource_version: int, review_id: str,
    ) -> ClaimEvidenceRetrievalSessionV1 | None: ...

    @abstractmethod
    def create_session(
        self, session: ClaimEvidenceRetrievalSessionV1,
    ) -> ClaimEvidenceRetrievalSessionV1: ...

    @abstractmethod
    def update_session(
        self,
        session_id: str,
        *,
        expected_status: ClaimEvidenceRetrievalStatus,
        status: ClaimEvidenceRetrievalStatus,
        reason_code: str | None = None,
        query_count: int | None = None,
        evidence_scope_ids: list[str] | None = None,
        hard_block_reason: str | None = None,
        now: datetime | None = None,
    ) -> ClaimEvidenceRetrievalSessionV1: ...

    # ---- batches ----------------------------------------------------
    @abstractmethod
    def save_batch(self, batch: ClaimEvidenceRetrievalBatchV1) -> ClaimEvidenceRetrievalBatchV1: ...

    @abstractmethod
    def get_batch(self, batch_id: str) -> ClaimEvidenceRetrievalBatchV1 | None: ...

    @abstractmethod
    def list_batches(self, session_id: str) -> list[ClaimEvidenceRetrievalBatchV1]: ...

    @abstractmethod
    def complete_retrieval_batch(
        self,
        *,
        batch_id: str,
        run_id: str,
        step_id: str,
        owner: str,
        epoch: int,
        output_hash: str,
        payload: dict[str, Any],
        evidence: Sequence[PersistedEvidenceSnapshot],
        now: datetime,
    ) -> None: ...

    @abstractmethod
    def save_rejudge_batch(
        self,
        *,
        batch_id: str,
        output_hash: str,
        payload: dict[str, Any],
        supplements: Sequence[ClaimSupplementJudgementV1],
        hard_block_reason: str | None,
        now: datetime,
    ) -> None: ...

    # ---- scopes, activation and reads --------------------------------
    @abstractmethod
    def save_evidence_set(self, scope: ClaimReviewEvidenceSetV1) -> ClaimReviewEvidenceSetV1: ...

    @abstractmethod
    def list_evidence_sets(self, run_ids: Sequence[str]) -> list[ClaimReviewEvidenceSetV1]: ...

    @abstractmethod
    def activate_session(
        self,
        *,
        session_id: str,
        scope: ClaimReviewEvidenceSetV1,
        round_one_hash: str,
        supported: int,
        contradicted: int,
        absent: int,
        factual: int,
        claim_total: int,
        now: datetime,
    ) -> ClaimEvidenceRetrievalSessionV1: ...

    @abstractmethod
    def list_sessions(self, run_ids: Sequence[str]) -> list[ClaimEvidenceRetrievalSessionV1]: ...

    @abstractmethod
    def list_supplements(self, run_ids: Sequence[str]) -> list[ClaimSupplementJudgementV1]: ...

    @abstractmethod
    def list_history(self, run_id: str) -> tuple[list[Any], list[Any], list[Any]]: ...

    # ---- shared validation ------------------------------------------
    @staticmethod
    def _check_payload(payload: dict[str, Any]) -> None:
        if payload_bytes(payload) > 1024 * 1024:
            raise PersistenceConflict("supplement payload exceeds 1 MiB")

    @staticmethod
    def _check_round_one(
        *,
        target_claim_ids: Sequence[str],
        persisted: Sequence[dict[str, Any]],
        round_one_hash: str,
    ) -> None:
        """Validate the persisted round-1 set against the metric snapshot.

        The activation caller computes the effective metric from the round-1
        view it is about to activate.  Comparing that identity with the rows read
        inside the write transaction keeps the review summary, the activated
        session and the stored judgements in one consistent state.
        """

        targets = set(target_claim_ids)
        if not targets:
            raise PersistenceConflict("supplement session has no target claims")
        if {str(item["claim_id"]) for item in persisted} != targets:
            raise PersistenceConflict("supplement activation is incomplete")
        if any(
            str(item["status"]) != ClaimJudgementStatus.COMPLETED.value
            for item in persisted
        ):
            raise PersistenceConflict("supplement activation contains an incomplete judgement")
        if round_one_identity_from_records(persisted) != round_one_hash:
            raise PersistenceConflict("supplement activation metric set differs from the round")

    @staticmethod
    def _upsert_scope(db, scope: ClaimReviewEvidenceSetV1) -> None:
        """Idempotent scope write shared by activation and direct saves.

        The same identity with the same content is a replay; a different hash for
        the same scope identity, or a different scope for the same
        ``(run, resource, version, purpose, session)`` binding, is a conflict.
        """

        row = db.get(ClaimReviewEvidenceSetORM, scope.scope_id)
        if row is not None:
            if row.manifest_hash != scope.manifest_hash:
                raise PersistenceConflict("evidence scope payload conflict")
            return
        bound = (
            db.query(ClaimReviewEvidenceSetORM)
            .filter_by(
                run_id=scope.run_id, resource_id=scope.resource_id,
                resource_version=scope.resource_version, purpose=scope.purpose,
                session_id=scope.session_id,
            )
            .first()
        )
        if bound is not None:
            raise PersistenceConflict("evidence scope identity conflict")
        db.add(ClaimReviewEvidenceSetORM(
            scope_id=scope.scope_id,
            run_id=scope.run_id,
            resource_id=scope.resource_id,
            resource_version=scope.resource_version,
            review_id=scope.review_id,
            purpose=scope.purpose,
            session_id=scope.session_id,
            base_evidence_ids=list(scope.base_evidence_ids),
            added_evidence_ids=list(scope.added_evidence_ids),
            snapshot_hashes=dict(scope.snapshot_hashes),
            manifest=list(scope.manifest),
            manifest_hash=scope.manifest_hash,
            parent_scope_id=scope.parent_scope_id,
            created_at=scope.created_at,
        ))

    @staticmethod
    def _check_transition(current: str, target: str) -> None:
        if target == current:
            return
        if target not in CLAIM_EVIDENCE_BATCH_TRANSITIONS.get(current, frozenset()):
            raise PersistenceConflict(f"illegal batch transition {current} -> {target}")

    @staticmethod
    def _check_terminal(current: ClaimEvidenceRetrievalStatus, target: ClaimEvidenceRetrievalStatus) -> None:
        if current in TERMINAL_STATUSES and target != current:
            raise SupplementSessionClosed("terminal session is immutable")
        if current in TERMINAL_STATUSES:
            return
        allowed = {
            ClaimEvidenceRetrievalStatus.PENDING: {
                ClaimEvidenceRetrievalStatus.QUERYING,
                ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
                ClaimEvidenceRetrievalStatus.BLOCKED,
                ClaimEvidenceRetrievalStatus.INTERRUPTED,
            },
            ClaimEvidenceRetrievalStatus.QUERYING: {
                ClaimEvidenceRetrievalStatus.RETRIEVING,
                ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
                ClaimEvidenceRetrievalStatus.BLOCKED,
                ClaimEvidenceRetrievalStatus.INTERRUPTED,
            },
            ClaimEvidenceRetrievalStatus.RETRIEVING: {
                ClaimEvidenceRetrievalStatus.REJUDGING,
                ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
                ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
                ClaimEvidenceRetrievalStatus.BLOCKED,
                ClaimEvidenceRetrievalStatus.INTERRUPTED,
            },
            ClaimEvidenceRetrievalStatus.REJUDGING: {
                ClaimEvidenceRetrievalStatus.COMPLETED,
                ClaimEvidenceRetrievalStatus.UNAVAILABLE,
                ClaimEvidenceRetrievalStatus.BUDGET_EXHAUSTED,
                ClaimEvidenceRetrievalStatus.BLOCKED,
                ClaimEvidenceRetrievalStatus.INTERRUPTED,
            },
        }
        if target not in allowed.get(current, set()):
            raise PersistenceConflict(f"illegal session transition {current.value} -> {target.value}")


class SQLClaimSupplementRepository(BaseClaimSupplementRepository):
    def __init__(self, *, claim_repository, audit_repository, session_factory: Callable[[], Session]):
        super().__init__(claim_repository=claim_repository, audit_repository=audit_repository)
        self.session_factory = session_factory

    # ---- mapping helpers -------------------------------------------
    @staticmethod
    def _ledger(row: ClaimEvidenceRetrievalRunORM) -> SupplementRunLedger:
        return SupplementRunLedger(
            run_id=row.run_id,
            policy_hash=row.policy_hash,
            policy=ClaimEvidenceRetrievalPolicyV1.model_validate(row.policy_json),
            revision=row.revision,
            reserved_tokens=int(row.reserved_tokens or 0),
            known_tokens=int(row.known_tokens or 0),
            unknown_tokens=int(row.unknown_tokens or 0),
            logical_calls=int(row.logical_calls or 0),
            attempts=int(row.attempts or 0),
            query_count=int(row.query_count or 0),
            owner=row.owner,
            epoch=int(row.epoch or 0),
            started_at=utc(row.started_at),
            deadline_at=utc(row.deadline_at),
            status=row.status,
        )

    @staticmethod
    def _session(row: ClaimEvidenceRetrievalSessionORM) -> ClaimEvidenceRetrievalSessionV1:
        return ClaimEvidenceRetrievalSessionV1(
            session_id=row.session_id,
            run_id=row.run_id,
            resource_id=row.resource_id,
            resource_version=row.resource_version,
            review_id=row.review_id,
            content_hash=row.content_hash,
            policy_hash=row.policy_hash,
            base_evidence_set_hash=row.base_evidence_set_hash,
            initial_judgement_hash=row.initial_judgement_hash,
            target_claim_ids=list(row.target_claim_ids or []),
            query_count=int(row.query_count or 0),
            evidence_scope_ids=list(row.evidence_scope_ids or []),
            status=ClaimEvidenceRetrievalStatus(row.status),
            reason_code=row.reason_code,
            active=bool(row.active),
            hard_block=bool(row.hard_block),
            hard_block_reason=row.hard_block_reason,
            created_at=utc(row.created_at),
            updated_at=utc(row.updated_at),
            completed_at=utc(row.completed_at),
        )

    @staticmethod
    def _batch(row: ClaimEvidenceRetrievalBatchORM) -> ClaimEvidenceRetrievalBatchV1:
        return ClaimEvidenceRetrievalBatchV1(
            batch_id=row.batch_id,
            session_id=row.session_id,
            kind=ClaimEvidenceBatchKind(row.kind),
            ordinal=row.ordinal,
            input_hash=row.input_hash,
            output_hash=row.output_hash,
            status=ClaimEvidenceBatchStatus(row.status),
            payload=dict(row.payload or {}),
            expected_claim_ids=list(row.expected_claim_ids or []),
            created_at=utc(row.created_at),
            updated_at=utc(row.updated_at),
        )

    @staticmethod
    def _scope(row: ClaimReviewEvidenceSetORM) -> ClaimReviewEvidenceSetV1:
        return ClaimReviewEvidenceSetV1(
            scope_id=row.scope_id,
            run_id=row.run_id,
            resource_id=row.resource_id,
            resource_version=row.resource_version,
            review_id=row.review_id,
            purpose=row.purpose,
            session_id=row.session_id,
            base_evidence_ids=list(row.base_evidence_ids or []),
            added_evidence_ids=list(row.added_evidence_ids or []),
            snapshot_hashes=dict(row.snapshot_hashes or {}),
            manifest=list(row.manifest or []),
            manifest_hash=row.manifest_hash,
            parent_scope_id=row.parent_scope_id,
            created_at=utc(row.created_at),
        )

    @staticmethod
    def _supplement(row: ClaimSupplementJudgementORM, evidence: Iterable[str]) -> ClaimSupplementJudgementV1:
        return ClaimSupplementJudgementV1(
            judgement_id=row.judgement_id,
            session_id=row.session_id,
            claim_id=row.claim_id,
            run_id=row.run_id,
            resource_id=row.resource_id,
            resource_version=row.resource_version,
            review_id=row.review_id,
            round_no=1,
            scope_id=row.scope_id,
            status=ClaimJudgementStatus(row.status),
            verdict=row.verdict,
            evidence_ids=sorted(evidence),
            conflicting_evidence_ids=list(row.conflicting_evidence_ids or []),
            evidence_conflict=bool(row.evidence_conflict),
            reason=row.reason,
            judge_model=row.judge_model,
            judge_prompt_version=row.judge_prompt_version,
            confidence=row.confidence,
            payload_hash=row.payload_hash,
            created_at=utc(row.created_at),
        )

    # ---- run ledger -------------------------------------------------
    def get_run(self, run_id: str) -> SupplementRunLedger | None:
        with self.session_factory() as db:
            row = db.get(ClaimEvidenceRetrievalRunORM, run_id)
            return self._ledger(row) if row is not None else None

    def open_run(
        self,
        *,
        run_id: str,
        policy: ClaimEvidenceRetrievalPolicyV1,
        started_at: datetime,
        deadline_at: datetime,
        owner: str | None = None,
        epoch: int = 0,
    ) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = db.get(ClaimEvidenceRetrievalRunORM, run_id)
                if row is not None:
                    if row.policy_hash != policy.policy_hash:
                        raise PersistenceConflict("supplement policy differs from the frozen run")
                    return self._ledger(row)
                row = ClaimEvidenceRetrievalRunORM(
                    run_id=run_id,
                    policy_hash=policy.policy_hash,
                    policy_json=policy.model_dump(mode="json"),
                    revision=0,
                    reserved_tokens=0,
                    known_tokens=0,
                    unknown_tokens=0,
                    logical_calls=0,
                    attempts=0,
                    query_count=0,
                    owner=owner,
                    epoch=epoch,
                    started_at=started_at,
                    deadline_at=deadline_at,
                    status=ClaimEvidenceRetrievalStatus.PENDING.value,
                )
                db.add(row)
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def reserve_attempt(
        self,
        *,
        run_id: str,
        owner: str,
        epoch: int,
        reserved_tokens: int,
        attempt_id: str,
        batch_id: str,
        logical_call_id: str,
        attempt_no: int,
        output_cap: int,
        now: datetime,
    ) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement ledger missing")
                policy = ClaimEvidenceRetrievalPolicyV1.model_validate(row.policy_json)
                if epoch < int(row.epoch or 0):
                    raise PersistenceConflict("stale supplement owner epoch")
                if (
                    row.attempts + 1 > policy.max_attempts
                    or row.unknown_tokens + row.known_tokens + row.reserved_tokens + reserved_tokens
                    > policy.max_estimated_tokens
                    or utc(row.deadline_at) <= now
                ):
                    raise SupplementBudgetExceeded("supplement token/attempt budget exhausted")
                existing = db.get(ClaimEvidenceRetrievalAttemptORM, attempt_id)
                if existing is not None:
                    if (
                        existing.reserved_tokens != reserved_tokens
                        or existing.logical_call_id != logical_call_id
                    ):
                        raise PersistenceConflict("attempt reservation replay differs")
                    return self._ledger(row)
                db.add(ClaimEvidenceRetrievalAttemptORM(
                    attempt_id=attempt_id,
                    batch_id=batch_id,
                    logical_call_id=logical_call_id,
                    attempt_no=attempt_no,
                    owner=owner,
                    epoch=epoch,
                    reserved_tokens=reserved_tokens,
                    output_cap=output_cap,
                    status=ClaimEvidenceAttemptStatus.RESERVED.value,
                    started_at=now,
                ))
                row.reserved_tokens = int(row.reserved_tokens or 0) + reserved_tokens
                row.attempts = int(row.attempts or 0) + 1
                row.owner = owner
                row.epoch = max(int(row.epoch or 0), epoch)
                row.revision = int(row.revision or 0) + 1
                row.updated_at = now
                batch = db.get(ClaimEvidenceRetrievalBatchORM, batch_id)
                if batch is not None:
                    if batch.status == ClaimEvidenceBatchStatus.PLANNED.value:
                        self._check_transition(batch.status, ClaimEvidenceBatchStatus.RESERVED.value)
                        batch.status = ClaimEvidenceBatchStatus.RESERVED.value
                        batch.updated_at = now
                    elif batch.status not in {
                        ClaimEvidenceBatchStatus.RESERVED.value,
                        ClaimEvidenceBatchStatus.DISPATCHED.value,
                    }:
                        # A later physical attempt of the same logical call keeps
                        # the batch in its reserved/dispatched state; a terminal
                        # batch cannot accept a new reservation.
                        raise PersistenceConflict("batch cannot accept another attempt")
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def mark_dispatched(
        self, *, run_id: str, attempt_id: str, owner: str, epoch: int, now: datetime,
    ) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement ledger missing")
                if int(row.epoch or 0) != epoch or row.owner != owner:
                    raise PersistenceConflict("stale supplement owner cannot dispatch")
                attempt = db.get(ClaimEvidenceRetrievalAttemptORM, attempt_id)
                if attempt is None:
                    raise PersistenceConflict("attempt reservation missing")
                if attempt.status == ClaimEvidenceAttemptStatus.DISPATCHING.value:
                    return self._ledger(row)
                if attempt.status != ClaimEvidenceAttemptStatus.RESERVED.value:
                    raise PersistenceConflict("attempt already settled")
                attempt.status = ClaimEvidenceAttemptStatus.DISPATCHING.value
                batch = db.get(ClaimEvidenceRetrievalBatchORM, attempt.batch_id)
                if batch is not None and batch.status == ClaimEvidenceBatchStatus.RESERVED.value:
                    self._check_transition(batch.status, ClaimEvidenceBatchStatus.DISPATCHED.value)
                    batch.status = ClaimEvidenceBatchStatus.DISPATCHED.value
                    batch.updated_at = now
                row.revision = int(row.revision or 0) + 1
                row.updated_at = now
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def settle_attempt(
        self,
        *,
        run_id: str,
        attempt_id: str,
        owner: str,
        epoch: int,
        status: ClaimEvidenceAttemptStatus,
        known_tokens: int | None,
        now: datetime,
    ) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        allowed_from = {
            ClaimEvidenceAttemptStatus.NOT_SENT.value: {ClaimEvidenceAttemptStatus.RESERVED.value},
            ClaimEvidenceAttemptStatus.SUCCEEDED.value: {ClaimEvidenceAttemptStatus.DISPATCHING.value},
            ClaimEvidenceAttemptStatus.FAILED.value: {
                ClaimEvidenceAttemptStatus.DISPATCHING.value,
                ClaimEvidenceAttemptStatus.RESERVED.value,
            },
            ClaimEvidenceAttemptStatus.USAGE_UNKNOWN.value: {
                ClaimEvidenceAttemptStatus.DISPATCHING.value,
                ClaimEvidenceAttemptStatus.RESERVED.value,
            },
        }
        if status.value not in allowed_from:
            raise PersistenceConflict("unsupported attempt settlement")

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement ledger missing")
                if int(row.epoch or 0) != epoch or row.owner != owner:
                    raise PersistenceConflict("stale supplement owner cannot settle")
                attempt = db.get(ClaimEvidenceRetrievalAttemptORM, attempt_id)
                if attempt is None:
                    raise PersistenceConflict("attempt reservation missing")
                if attempt.status not in allowed_from[status.value]:
                    if attempt.status == status.value and attempt.known_tokens == known_tokens:
                        return self._ledger(row)
                    raise PersistenceConflict("attempt already settled")
                attempt.status = status.value
                attempt.known_tokens = known_tokens
                attempt.unknown_usage = (known_tokens is None
                                         and status is not ClaimEvidenceAttemptStatus.NOT_SENT)
                attempt.ended_at = now
                row.reserved_tokens = max(0, int(row.reserved_tokens or 0) - attempt.reserved_tokens)
                if status is ClaimEvidenceAttemptStatus.NOT_SENT:
                    # Definitively not dispatched: release the token reservation
                    # but keep the attempt row and the physical attempt count.
                    pass
                elif known_tokens is None:
                    # Unknown usage keeps the reserve charged; never record zero.
                    row.unknown_tokens = int(row.unknown_tokens or 0) + attempt.reserved_tokens
                else:
                    row.known_tokens = int(row.known_tokens or 0) + known_tokens
                row.revision = int(row.revision or 0) + 1
                row.updated_at = now
                batch = db.get(ClaimEvidenceRetrievalBatchORM, attempt.batch_id)
                if (batch is not None and batch.status == ClaimEvidenceBatchStatus.RESERVED.value
                        and status is not ClaimEvidenceAttemptStatus.NOT_SENT):
                    batch.status = ClaimEvidenceBatchStatus.DISPATCHED.value
                    batch.updated_at = now
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def list_attempts(self, run_id: str) -> list[ClaimEvidenceRetrievalAttemptV1]:
        with self.session_factory() as db:
            rows = (
                db.query(ClaimEvidenceRetrievalAttemptORM)
                .join(
                    ClaimEvidenceRetrievalBatchORM,
                    ClaimEvidenceRetrievalAttemptORM.batch_id == ClaimEvidenceRetrievalBatchORM.batch_id,
                )
                .join(
                    ClaimEvidenceRetrievalSessionORM,
                    ClaimEvidenceRetrievalBatchORM.session_id == ClaimEvidenceRetrievalSessionORM.session_id,
                )
                .filter(ClaimEvidenceRetrievalSessionORM.run_id == run_id)
                .order_by(
                    ClaimEvidenceRetrievalAttemptORM.started_at,
                    ClaimEvidenceRetrievalAttemptORM.attempt_id,
                )
                .all()
            )
            return [ClaimEvidenceRetrievalAttemptV1(
                attempt_id=row.attempt_id, batch_id=row.batch_id,
                logical_call_id=row.logical_call_id, attempt_no=row.attempt_no,
                owner=row.owner, epoch=int(row.epoch or 0),
                reserved_tokens=int(row.reserved_tokens or 0),
                output_cap=int(row.output_cap or 1),
                known_tokens=row.known_tokens,
                status=ClaimEvidenceAttemptStatus(row.status),
                unknown_usage=bool(row.unknown_usage),
                started_at=utc(row.started_at), ended_at=utc(row.ended_at) if row.ended_at else None,
            ) for row in rows]

    def interrupt_runs(
        self, run_ids: Sequence[str], *, now: datetime, reason_code: str = "run_interrupted",
    ) -> int:
        ids = [item for item in dict.fromkeys(run_ids) if item]
        if not ids:
            return 0
        from app.db.shared.retry import run_with_sqlite_retry

        in_flight = {status.value for status in (
            ClaimEvidenceRetrievalStatus.PENDING,
            ClaimEvidenceRetrievalStatus.QUERYING,
            ClaimEvidenceRetrievalStatus.RETRIEVING,
            ClaimEvidenceRetrievalStatus.REJUDGING,
        )}

        def once() -> int:
            with self.session_factory() as db:
                runs = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter(ClaimEvidenceRetrievalRunORM.run_id.in_(ids))
                    .with_for_update()
                    .all()
                )
                ledgers = {row.run_id: row for row in runs}
                sessions = (
                    db.query(ClaimEvidenceRetrievalSessionORM)
                    .filter(ClaimEvidenceRetrievalSessionORM.run_id.in_(ids),
                            ClaimEvidenceRetrievalSessionORM.status.in_(in_flight))
                    .order_by(ClaimEvidenceRetrievalSessionORM.session_id)
                    .all()
                )
                if not sessions:
                    return 0
                row_by_session = {item.session_id: item for item in sessions}
                attempts = (
                    db.query(ClaimEvidenceRetrievalAttemptORM)
                    .join(
                        ClaimEvidenceRetrievalBatchORM,
                        ClaimEvidenceRetrievalAttemptORM.batch_id == ClaimEvidenceRetrievalBatchORM.batch_id,
                    )
                    .filter(
                        ClaimEvidenceRetrievalBatchORM.session_id.in_(list(row_by_session)),
                        ClaimEvidenceRetrievalAttemptORM.status.in_({
                            ClaimEvidenceAttemptStatus.RESERVED.value,
                            ClaimEvidenceAttemptStatus.DISPATCHING.value,
                        }),
                    )
                    .all()
                )
                for attempt in attempts:
                    batch = db.get(ClaimEvidenceRetrievalBatchORM, attempt.batch_id)
                    ledger = ledgers.get(row_by_session[batch.session_id].run_id)
                    if ledger is None:
                        continue
                    ledger.reserved_tokens = max(
                        0, int(ledger.reserved_tokens or 0) - int(attempt.reserved_tokens or 0))
                    if attempt.status == ClaimEvidenceAttemptStatus.DISPATCHING.value:
                        # The send boundary was committed: provider capacity may
                        # already be consumed, so keep the reserve as unknown.
                        attempt.status = ClaimEvidenceAttemptStatus.USAGE_UNKNOWN.value
                        attempt.unknown_usage = True
                        ledger.unknown_tokens = (
                            int(ledger.unknown_tokens or 0) + int(attempt.reserved_tokens or 0))
                    else:
                        attempt.status = ClaimEvidenceAttemptStatus.NOT_SENT.value
                        attempt.unknown_usage = False
                    attempt.ended_at = now
                    ledger.revision = int(ledger.revision or 0) + 1
                    ledger.updated_at = now
                    if batch.status in {
                        ClaimEvidenceBatchStatus.RESERVED.value,
                        ClaimEvidenceBatchStatus.DISPATCHED.value,
                    }:
                        batch.status = ClaimEvidenceBatchStatus.INTERRUPTED.value
                        batch.updated_at = now
                for session in sessions:
                    session.status = ClaimEvidenceRetrievalStatus.INTERRUPTED.value
                    session.reason_code = reason_code
                    session.completed_at = now
                    session.updated_at = now
                db.commit()
                return len(sessions)

        return run_with_sqlite_retry(once)

    def count_logical_call(
        self, *, run_id: str, owner: str, epoch: int, now: datetime,
    ) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement ledger missing")
                if row.owner != owner or int(row.epoch or 0) != epoch:
                    raise PersistenceConflict("stale supplement owner cannot start a call")
                policy = ClaimEvidenceRetrievalPolicyV1.model_validate(row.policy_json)
                if int(row.logical_calls or 0) + 1 > policy.max_logical_calls:
                    raise SupplementBudgetExceeded("supplement logical call budget exhausted")
                row.logical_calls = int(row.logical_calls or 0) + 1
                row.revision = int(row.revision or 0) + 1
                row.updated_at = now
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def record_query_count(self, *, run_id: str, count: int) -> SupplementRunLedger:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> SupplementRunLedger:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement ledger missing")
                policy = ClaimEvidenceRetrievalPolicyV1.model_validate(row.policy_json)
                total = int(row.query_count or 0) + count
                if total > policy.max_queries:
                    raise SupplementBudgetExceeded("supplement query budget exhausted")
                row.query_count = total
                row.revision = int(row.revision or 0) + 1
                db.commit()
                return self._ledger(row)

        return run_with_sqlite_retry(once)

    def touch_run(self, *, run_id: str, status: str, owner: str, epoch: int) -> None:
        with self.session_factory() as db:
            row = (
                db.query(ClaimEvidenceRetrievalRunORM)
                .filter_by(run_id=run_id)
                .with_for_update()
                .first()
            )
            if row is None:
                return
            if int(row.epoch or 0) != epoch or row.owner != owner:
                raise PersistenceConflict("stale supplement owner cannot update the ledger")
            row.status = status
            row.updated_at = datetime.now(timezone.utc)
            db.commit()

    # ---- sessions ---------------------------------------------------
    def get_session(self, session_id: str) -> ClaimEvidenceRetrievalSessionV1 | None:
        with self.session_factory() as db:
            row = db.get(ClaimEvidenceRetrievalSessionORM, session_id)
            return self._session(row) if row is not None else None

    def find_session(
        self, *, run_id: str, resource_id: str, resource_version: int, review_id: str,
    ) -> ClaimEvidenceRetrievalSessionV1 | None:
        with self.session_factory() as db:
            row = (
                db.query(ClaimEvidenceRetrievalSessionORM)
                .filter_by(
                    run_id=run_id, resource_id=resource_id,
                    resource_version=resource_version, review_id=review_id,
                )
                .first()
            )
            return self._session(row) if row is not None else None

    def create_session(
        self, session: ClaimEvidenceRetrievalSessionV1,
    ) -> ClaimEvidenceRetrievalSessionV1:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> ClaimEvidenceRetrievalSessionV1:
            with self.session_factory() as db:
                from app.db.claim.publication import lock_sql_resource, publication_barrier_reason, revoke_sql_publication

                from app.db.generation.fencing import assert_execution_ownership
                assert_execution_ownership(db, session.run_id)
                lock_sql_resource(db, session.resource_id)
                existing = db.get(ClaimEvidenceRetrievalSessionORM, session.session_id)
                if existing is not None:
                    return self._session(existing)
                bound = (
                    db.query(ClaimEvidenceRetrievalSessionORM)
                    .filter_by(
                        run_id=session.run_id, resource_id=session.resource_id,
                        resource_version=session.resource_version, review_id=session.review_id,
                    )
                    .first()
                )
                if bound is not None:
                    raise PersistenceConflict("a supplement session already exists for this version")
                db.add(ClaimEvidenceRetrievalSessionORM(
                    session_id=session.session_id,
                    run_id=session.run_id,
                    resource_id=session.resource_id,
                    resource_version=session.resource_version,
                    review_id=session.review_id,
                    content_hash=session.content_hash,
                    policy_hash=session.policy_hash,
                    base_evidence_set_hash=session.base_evidence_set_hash,
                    initial_judgement_hash=session.initial_judgement_hash,
                    target_claim_ids=list(session.target_claim_ids),
                    query_count=session.query_count,
                    evidence_scope_ids=list(session.evidence_scope_ids),
                    status=session.status.value,
                    reason_code=session.reason_code,
                    active=False,
                    hard_block=session.hard_block,
                    hard_block_reason=session.hard_block_reason,
                    created_at=session.created_at,
                    updated_at=session.updated_at,
                    completed_at=session.completed_at,
                ))
                if publication_barrier_reason(status=session.status, hard_block=session.hard_block):
                    revoke_sql_publication(
                        db, run_id=session.run_id, resource_id=session.resource_id,
                        resource_version=session.resource_version,
                    )
                db.commit()
                return session

        return run_with_sqlite_retry(once)

    def update_session(
        self,
        session_id: str,
        *,
        expected_status: ClaimEvidenceRetrievalStatus,
        status: ClaimEvidenceRetrievalStatus,
        reason_code: str | None = None,
        query_count: int | None = None,
        evidence_scope_ids: list[str] | None = None,
        hard_block_reason: str | None = None,
        now: datetime | None = None,
    ) -> ClaimEvidenceRetrievalSessionV1:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> ClaimEvidenceRetrievalSessionV1:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalSessionORM)
                    .filter_by(session_id=session_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement session missing")
                current = ClaimEvidenceRetrievalStatus(row.status)
                if current != expected_status:
                    if current == status:
                        return self._session(row)
                    raise PersistenceConflict("session CAS mismatch")
                self._check_terminal(current, status)
                stamped = now or datetime.now(timezone.utc)
                row.status = status.value
                row.reason_code = reason_code
                row.updated_at = stamped
                if query_count is not None:
                    row.query_count = query_count
                if evidence_scope_ids is not None:
                    row.evidence_scope_ids = list(evidence_scope_ids)
                if hard_block_reason is not None:
                    row.hard_block = True
                    row.hard_block_reason = hard_block_reason
                if status in TERMINAL_STATUSES:
                    row.completed_at = stamped
                db.commit()
                return self._session(row)

        return run_with_sqlite_retry(once)

    # ---- batches ----------------------------------------------------
    def save_batch(self, batch: ClaimEvidenceRetrievalBatchV1) -> ClaimEvidenceRetrievalBatchV1:
        from app.db.shared.retry import run_with_sqlite_retry

        self._check_payload(batch.payload)

        def once() -> ClaimEvidenceRetrievalBatchV1:
            with self.session_factory() as db:
                row = db.get(ClaimEvidenceRetrievalBatchORM, batch.batch_id)
                if row is not None:
                    if row.input_hash != batch.input_hash or row.kind != batch.kind.value:
                        raise PersistenceConflict("batch identity payload conflict")
                    if batch.kind is ClaimEvidenceBatchKind.QUERY and batch.status is ClaimEvidenceBatchStatus.COMPLETED:
                        if row.status == ClaimEvidenceBatchStatus.COMPLETED.value:
                            if row.output_hash != batch.output_hash:
                                raise PersistenceConflict("completed query batch differs")
                        else:
                            self._check_transition(row.status, batch.status.value)
                            row.status = batch.status.value
                            row.output_hash = batch.output_hash
                            row.payload = batch.payload
                            row.updated_at = batch.updated_at
                            db.commit()
                    return self._batch(row)
                db.add(ClaimEvidenceRetrievalBatchORM(
                    batch_id=batch.batch_id,
                    session_id=batch.session_id,
                    kind=batch.kind.value,
                    ordinal=batch.ordinal,
                    input_hash=batch.input_hash,
                    output_hash=batch.output_hash,
                    status=batch.status.value,
                    payload=batch.payload,
                    expected_claim_ids=list(batch.expected_claim_ids),
                    created_at=batch.created_at,
                    updated_at=batch.updated_at,
                ))
                db.commit()
                return batch

        return run_with_sqlite_retry(once)

    def get_batch(self, batch_id: str) -> ClaimEvidenceRetrievalBatchV1 | None:
        with self.session_factory() as db:
            row = db.get(ClaimEvidenceRetrievalBatchORM, batch_id)
            return self._batch(row) if row is not None else None

    def list_batches(self, session_id: str) -> list[ClaimEvidenceRetrievalBatchV1]:
        with self.session_factory() as db:
            rows = (
                db.query(ClaimEvidenceRetrievalBatchORM)
                .filter_by(session_id=session_id)
                .order_by(ClaimEvidenceRetrievalBatchORM.kind, ClaimEvidenceRetrievalBatchORM.ordinal)
                .all()
            )
            return [self._batch(row) for row in rows]

    def complete_retrieval_batch(
        self,
        *,
        batch_id: str,
        run_id: str,
        step_id: str,
        owner: str,
        epoch: int,
        output_hash: str,
        payload: dict[str, Any],
        evidence: Sequence[PersistedEvidenceSnapshot],
        now: datetime,
    ) -> None:
        from app.db.shared.retry import run_with_sqlite_retry

        self._check_payload(payload)
        _validate_append(
            run_id=run_id, step_id=step_id,
            knowledge_base_id=self.audit_repository.get_run(run_id).knowledge_base_id
            if self.audit_repository is not None else None,
            evidence=evidence,
        )

        def once() -> None:
            with self.session_factory() as db:
                batch = (
                    db.query(ClaimEvidenceRetrievalBatchORM)
                    .filter_by(batch_id=batch_id)
                    .with_for_update()
                    .first()
                )
                if batch is None:
                    raise PersistenceConflict("retrieval batch missing")
                if batch.status == ClaimEvidenceBatchStatus.COMPLETED.value:
                    if batch.output_hash != output_hash:
                        raise PersistenceConflict("completed retrieval batch differs")
                    return
                run = (
                    db.query(ClaimEvidenceRetrievalRunORM)
                    .filter_by(run_id=run_id)
                    .with_for_update()
                    .first()
                )
                if run is None or run.owner != owner or int(run.epoch or 0) != epoch:
                    raise PersistenceConflict("stale supplement owner cannot append evidence")
                # Same business transaction: new snapshots, then batch status.
                self.audit_repository.append_step_evidence_in_session(
                    db,
                    run_id=run_id,
                    step_id=step_id,
                    evidence=evidence,
                    now=now,
                )
                self._check_transition(batch.status, ClaimEvidenceBatchStatus.COMPLETED.value)
                batch.status = ClaimEvidenceBatchStatus.COMPLETED.value
                batch.output_hash = output_hash
                batch.payload = payload
                batch.updated_at = now
                db.commit()

        run_with_sqlite_retry(once)

    def save_rejudge_batch(
        self,
        *,
        batch_id: str,
        output_hash: str,
        payload: dict[str, Any],
        supplements: Sequence[ClaimSupplementJudgementV1],
        hard_block_reason: str | None,
        now: datetime,
    ) -> None:
        from app.db.shared.models import RetrievalEvidenceSnapshotORM
        from app.db.shared.retry import run_with_sqlite_retry

        self._check_payload(payload)

        def once() -> None:
            with self.session_factory() as db:
                from app.db.claim.publication import revoke_sql_publication
                batch = (
                    db.query(ClaimEvidenceRetrievalBatchORM)
                    .filter_by(batch_id=batch_id)
                    .with_for_update()
                    .first()
                )
                if batch is None:
                    raise PersistenceConflict("rejudge batch missing")
                from app.db.generation.fencing import assert_execution_ownership
                bound_session = db.get(ClaimEvidenceRetrievalSessionORM, batch.session_id)
                if bound_session is None:
                    raise PersistenceConflict("supplement session missing")
                assert_execution_ownership(db, bound_session.run_id)
                if batch.status == ClaimEvidenceBatchStatus.COMPLETED.value:
                    if batch.output_hash != output_hash:
                        raise PersistenceConflict("completed rejudge batch differs")
                    return
                expected = set(batch.expected_claim_ids or [])
                if {item.claim_id for item in supplements} != expected:
                    raise PersistenceConflict("rejudge batch does not cover its expected claims")
                evidence_ids = {
                    evidence_id for item in supplements for evidence_id in item.evidence_ids
                } | {
                    evidence_id for item in supplements
                    for evidence_id in item.conflicting_evidence_ids
                }
                snapshots = {
                    row.evidence_id: row
                    for row in db.query(RetrievalEvidenceSnapshotORM)
                    .filter(RetrievalEvidenceSnapshotORM.evidence_id.in_(evidence_ids or {""}))
                    .all()
                }
                if set(snapshots) != evidence_ids:
                    raise PersistenceConflict("supplement judgement references missing evidence")
                for item in supplements:
                    if any(snapshots[evidence_id].run_id != item.run_id for evidence_id in evidence_ids):
                        raise PersistenceConflict("supplement evidence crosses the run boundary")
                    existing = db.get(ClaimSupplementJudgementORM, item.judgement_id)
                    if existing is not None:
                        if existing.payload_hash != item.payload_hash:
                            raise PersistenceConflict("supplement judgement payload conflict")
                        continue
                    db.add(ClaimSupplementJudgementORM(
                        judgement_id=item.judgement_id,
                        session_id=item.session_id,
                        claim_id=item.claim_id,
                        run_id=item.run_id,
                        resource_id=item.resource_id,
                        resource_version=item.resource_version,
                        review_id=item.review_id,
                        round_no=1,
                        scope_id=item.scope_id,
                        status=item.status.value,
                        verdict=item.verdict.value if item.verdict else None,
                        reason=item.reason,
                        judge_model=item.judge_model,
                        judge_prompt_version=item.judge_prompt_version,
                        confidence=item.confidence,
                        evidence_conflict=item.evidence_conflict,
                        conflicting_evidence_ids=list(item.conflicting_evidence_ids),
                        payload_hash=item.payload_hash,
                        created_at=item.created_at,
                    ))
                    db.flush()
                    for evidence_id in sorted(set(item.evidence_ids) | set(item.conflicting_evidence_ids)):
                        digest = hashlib.sha256(
                            f"{item.judgement_id}\x1f{evidence_id}".encode()
                        ).hexdigest()[:32]
                        db.add(ClaimSupplementEvidenceORM(
                            binding_id=f"csev_{digest}",
                            judgement_id=item.judgement_id,
                            evidence_id=evidence_id,
                            run_id=item.run_id,
                        ))
                if hard_block_reason is not None:
                    session = (
                        db.query(ClaimEvidenceRetrievalSessionORM)
                        .filter_by(session_id=batch.session_id)
                        .with_for_update()
                        .first()
                    )
                    if session is None:
                        raise PersistenceConflict("supplement session missing")
                    # false -> true only; never reset on activation or failure.
                    session.hard_block = True
                    session.hard_block_reason = hard_block_reason
                    session.updated_at = now
                    # Version-level safety stamp in the same transaction: a
                    # publication that already committed is withdrawn, and any
                    # later publish attempt is refused by the shared guard.
                    revoke_sql_publication(
                        db,
                        run_id=session.run_id,
                        resource_id=session.resource_id,
                        resource_version=session.resource_version,
                    )
                self._check_transition(batch.status, ClaimEvidenceBatchStatus.COMPLETED.value)
                batch.status = ClaimEvidenceBatchStatus.COMPLETED.value
                batch.output_hash = output_hash
                batch.payload = payload
                batch.updated_at = now
                db.commit()

        run_with_sqlite_retry(once)

    # ---- scopes and activation --------------------------------------
    def save_evidence_set(self, scope: ClaimReviewEvidenceSetV1) -> ClaimReviewEvidenceSetV1:
        from app.db.shared.retry import run_with_sqlite_retry

        def once() -> ClaimReviewEvidenceSetV1:
            with self.session_factory() as db:
                from app.db.generation.fencing import assert_execution_ownership
                assert_execution_ownership(db, scope.run_id)
                self._upsert_scope(db, scope)
                db.commit()
                return scope

        return run_with_sqlite_retry(once)

    def list_evidence_sets(self, run_ids: Sequence[str]) -> list[ClaimReviewEvidenceSetV1]:
        ids = list(dict.fromkeys(run_ids))
        with self.session_factory() as db:
            rows = (
                db.query(ClaimReviewEvidenceSetORM)
                .filter(ClaimReviewEvidenceSetORM.run_id.in_(ids or [""]))
                .order_by(
                    ClaimReviewEvidenceSetORM.run_id,
                    ClaimReviewEvidenceSetORM.resource_id,
                    ClaimReviewEvidenceSetORM.resource_version,
                )
                .all()
            )
            return [self._scope(row) for row in rows]

    def activate_session(
        self,
        *,
        session_id: str,
        scope: ClaimReviewEvidenceSetV1,
        round_one_hash: str,
        supported: int,
        contradicted: int,
        absent: int,
        factual: int,
        claim_total: int,
        now: datetime,
    ) -> ClaimEvidenceRetrievalSessionV1:
        from app.db.shared.retry import run_with_sqlite_retry
        from app.db.shared.models import ResourceReviewORM

        def once() -> ClaimEvidenceRetrievalSessionV1:
            with self.session_factory() as db:
                row = (
                    db.query(ClaimEvidenceRetrievalSessionORM)
                    .filter_by(session_id=session_id)
                    .with_for_update()
                    .first()
                )
                if row is None:
                    raise PersistenceConflict("supplement session missing")
                from app.db.generation.fencing import assert_execution_ownership
                assert_execution_ownership(db, row.run_id)
                persisted = (
                    db.query(ClaimSupplementJudgementORM)
                    .filter_by(session_id=session_id)
                    .all()
                )
                self._check_round_one(
                    target_claim_ids=list(row.target_claim_ids or []),
                    persisted=[
                        {
                            "claim_id": item.claim_id,
                            "judgement_id": item.judgement_id,
                            "status": item.status,
                            "verdict": item.verdict,
                        }
                        for item in persisted
                    ],
                    round_one_hash=round_one_hash,
                )
                if row.active:
                    # Replay of the same activation: the persisted round-1 set
                    # already matches, so no second write is needed.
                    return self._session(row)
                expected = ClaimEvidenceRetrievalStatus(row.status)
                self._check_terminal(expected, ClaimEvidenceRetrievalStatus.COMPLETED)
                existing = (
                    db.query(ClaimEvidenceRetrievalSessionORM)
                    .filter_by(
                        run_id=row.run_id, resource_id=row.resource_id,
                        resource_version=row.resource_version, review_id=row.review_id,
                        active=True,
                    )
                    .first()
                )
                if existing is not None:
                    raise PersistenceConflict("another session is already active")
                self._upsert_scope(db, scope)
                row.status = ClaimEvidenceRetrievalStatus.COMPLETED.value
                row.active = True
                row.query_count = int(row.query_count or 0)
                row.updated_at = now
                row.completed_at = now
                review = db.get(ResourceReviewORM, row.review_id)
                if review is None:
                    raise PersistenceConflict("supplement review missing")
                risk = contradicted + absent
                review.claim_total = claim_total
                review.claim_supported = supported
                review.claim_unsupported = risk
                review.suspected_hallucinations = risk
                review.claim_hallucination_rate = (risk / factual) if factual else 0.0
                review.claim_metric_status = "complete" if factual else "not_applicable"
                db.commit()
                return self._session(row)

        return run_with_sqlite_retry(once)

    def list_sessions(self, run_ids: Sequence[str]) -> list[ClaimEvidenceRetrievalSessionV1]:
        ids = list(dict.fromkeys(run_ids))
        with self.session_factory() as db:
            rows = (
                db.query(ClaimEvidenceRetrievalSessionORM)
                .filter(ClaimEvidenceRetrievalSessionORM.run_id.in_(ids or [""]))
                .order_by(
                    ClaimEvidenceRetrievalSessionORM.run_id,
                    ClaimEvidenceRetrievalSessionORM.resource_id,
                    ClaimEvidenceRetrievalSessionORM.resource_version,
                )
                .all()
            )
            return [self._session(row) for row in rows]

    def list_supplements(self, run_ids: Sequence[str]) -> list[ClaimSupplementJudgementV1]:
        ids = list(dict.fromkeys(run_ids))
        with self.session_factory() as db:
            rows = (
                db.query(ClaimSupplementJudgementORM)
                .filter(ClaimSupplementJudgementORM.run_id.in_(ids or [""]))
                .order_by(
                    ClaimSupplementJudgementORM.run_id,
                    ClaimSupplementJudgementORM.resource_id,
                    ClaimSupplementJudgementORM.resource_version,
                    ClaimSupplementJudgementORM.claim_id,
                )
                .all()
            )
            bindings: dict[str, list[str]] = {}
            for item in (
                db.query(ClaimSupplementEvidenceORM)
                .filter(ClaimSupplementEvidenceORM.run_id.in_(ids or [""]))
                .all()
            ):
                bindings.setdefault(item.judgement_id, []).append(item.evidence_id)
            return [self._supplement(row, bindings.get(row.judgement_id, [])) for row in rows]

    def list_history(self, run_id: str) -> tuple[list[Any], list[Any], list[Any]]:
        return (
            self.list_sessions([run_id]),
            self.list_supplements([run_id]),
            self.list_evidence_sets([run_id]),
        )


class MemoryClaimSupplementRepository(BaseClaimSupplementRepository):
    """Deep-copy mirror with manual audit→claim lock ordering."""

    # Set by ``bind_memory_publication_guard``; used only to withdraw an already
    # published version when a counter-evidence batch commits.
    resource_repository = None

    def __init__(self, *, claim_repository, audit_repository):
        super().__init__(claim_repository=claim_repository, audit_repository=audit_repository)
        self._lock = threading.RLock()
        self._ledgers: dict[str, SupplementRunLedger] = {}
        self._sessions: dict[str, ClaimEvidenceRetrievalSessionV1] = {}
        self._batches: dict[str, ClaimEvidenceRetrievalBatchV1] = {}
        self._attempts: dict[str, ClaimEvidenceRetrievalAttemptV1] = {}
        self._scopes: dict[str, ClaimReviewEvidenceSetV1] = {}
        self._supplements: dict[str, ClaimSupplementJudgementV1] = {}

    @contextmanager
    def _transaction(self):
        audit_lock = getattr(self.audit_repository, "_lock", None)
        with ExitStack() as stack:
            if audit_lock is not None:
                stack.enter_context(audit_lock)
            stack.enter_context(self._lock)
            yield

    def _assert_owned(self, run_id):
        """Called while the audit lock is held, before any memory mutation."""
        from app.core.execution import current_execution_fence, current_execution_session
        from app.db.generation.fencing import ExecutionLeaseLost

        fence, execution = current_execution_fence(), current_execution_session()
        identity = fence or execution
        if identity is None:
            return
        if identity.run_id != run_id or (execution is not None and (
            execution.run_id != run_id or execution.owner != identity.owner
        )):
            raise ExecutionLeaseLost()
        run = self.audit_repository._require_run(run_id)
        ledger = self._ledgers.get(run_id)
        if fence is not None and fence.epoch is not None and ledger is not None and fence.epoch != ledger.epoch:
            raise ExecutionLeaseLost()
        if (run["owner_instance_id"] != identity.owner
                or run["status"] not in {"created", "running", "finalizing"}
                or utc(run.get("lease_expires_at")) is None
                or utc(run["lease_expires_at"]) <= datetime.now(timezone.utc)):
            raise ExecutionLeaseLost()

    # ---- run ledger -------------------------------------------------
    def get_run(self, run_id: str) -> SupplementRunLedger | None:
        with self._transaction():
            item = self._ledgers.get(run_id)
            return replace(item) if item is not None else None

    def open_run(
        self, *, run_id, policy, started_at, deadline_at, owner=None, epoch=0,
    ) -> SupplementRunLedger:
        with self._transaction():
            self._assert_owned(run_id)
            existing = self._ledgers.get(run_id)
            if existing is not None:
                if existing.policy_hash != policy.policy_hash:
                    raise PersistenceConflict("supplement policy differs from the frozen run")
                return replace(existing)
            ledger = SupplementRunLedger(
                run_id=run_id, policy_hash=policy.policy_hash, policy=policy,
                revision=0, reserved_tokens=0, known_tokens=0, unknown_tokens=0,
                logical_calls=0, attempts=0, query_count=0,
                owner=owner, epoch=epoch,
                started_at=started_at, deadline_at=deadline_at,
                status=ClaimEvidenceRetrievalStatus.PENDING.value,
            )
            self._ledgers[run_id] = ledger
            return replace(ledger)

    def reserve_attempt(self, *, run_id, owner, epoch, reserved_tokens, attempt_id, batch_id,
                        logical_call_id, attempt_no, output_cap, now) -> SupplementRunLedger:
        with self._transaction():
            self._assert_owned(run_id)
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                raise PersistenceConflict("supplement ledger missing")
            policy = ledger.policy
            if epoch < ledger.epoch:
                raise PersistenceConflict("stale supplement owner epoch")
            if (
                ledger.attempts + 1 > policy.max_attempts
                or ledger.reserved_tokens + ledger.known_tokens + ledger.unknown_tokens
                + reserved_tokens > policy.max_estimated_tokens
                or ledger.deadline_at <= now
            ):
                raise SupplementBudgetExceeded("supplement token/attempt budget exhausted")
            existing = self._attempts.get(attempt_id)
            if existing is not None:
                if existing.reserved_tokens != reserved_tokens or existing.logical_call_id != logical_call_id:
                    raise PersistenceConflict("attempt reservation replay differs")
                return replace(ledger)
            self._attempts[attempt_id] = ClaimEvidenceRetrievalAttemptV1(
                attempt_id=attempt_id, batch_id=batch_id, logical_call_id=logical_call_id,
                attempt_no=attempt_no, owner=owner, epoch=epoch,
                reserved_tokens=reserved_tokens, output_cap=output_cap,
                status=ClaimEvidenceAttemptStatus.RESERVED, started_at=now,
            )
            batch = self._batches.get(batch_id)
            if batch is not None:
                if batch.status is ClaimEvidenceBatchStatus.PLANNED:
                    self._check_transition(batch.status.value, ClaimEvidenceBatchStatus.RESERVED.value)
                    self._batches[batch_id] = batch.model_copy(
                        update={"status": ClaimEvidenceBatchStatus.RESERVED, "updated_at": now},
                    )
                elif batch.status not in {
                    ClaimEvidenceBatchStatus.RESERVED, ClaimEvidenceBatchStatus.DISPATCHED,
                }:
                    raise PersistenceConflict("batch cannot accept another attempt")
            updated = replace(
                ledger,
                reserved_tokens=ledger.reserved_tokens + reserved_tokens,
                attempts=ledger.attempts + 1, owner=owner,
                epoch=max(ledger.epoch, epoch), revision=ledger.revision + 1,
            )
            self._ledgers[run_id] = updated
            return replace(updated)

    def mark_dispatched(self, *, run_id, attempt_id, owner, epoch, now) -> SupplementRunLedger:
        with self._transaction():
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                raise PersistenceConflict("supplement ledger missing")
            if ledger.epoch != epoch or ledger.owner != owner:
                raise PersistenceConflict("stale supplement owner cannot dispatch")
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise PersistenceConflict("attempt reservation missing")
            if attempt.status is ClaimEvidenceAttemptStatus.DISPATCHING:
                return replace(ledger)
            if attempt.status is not ClaimEvidenceAttemptStatus.RESERVED:
                raise PersistenceConflict("attempt already settled")
            self._attempts[attempt_id] = attempt.model_copy(
                update={"status": ClaimEvidenceAttemptStatus.DISPATCHING})
            batch = self._batches.get(attempt.batch_id)
            if batch is not None and batch.status is ClaimEvidenceBatchStatus.RESERVED:
                self._check_transition(batch.status.value, ClaimEvidenceBatchStatus.DISPATCHED.value)
                self._batches[batch.batch_id] = batch.model_copy(update={
                    "status": ClaimEvidenceBatchStatus.DISPATCHED, "updated_at": now,
                })
            updated = replace(ledger, revision=ledger.revision + 1)
            self._ledgers[run_id] = updated
            return replace(updated)

    def list_attempts(self, run_id) -> list[ClaimEvidenceRetrievalAttemptV1]:
        with self._transaction():
            batch_ids = {
                batch.batch_id for batch in self._batches.values()
                if batch.session_id in {
                    session.session_id for session in self._sessions.values()
                    if session.run_id == run_id
                }
            }
            return [
                attempt.model_copy(deep=True) for attempt in sorted(
                    (item for item in self._attempts.values() if item.batch_id in batch_ids),
                    key=lambda item: (item.started_at, item.attempt_id),
                )
            ]

    def settle_attempt(self, *, run_id, attempt_id, owner, epoch, status, known_tokens, now) -> SupplementRunLedger:
        allowed_from = {
            ClaimEvidenceAttemptStatus.NOT_SENT: {ClaimEvidenceAttemptStatus.RESERVED},
            ClaimEvidenceAttemptStatus.SUCCEEDED: {ClaimEvidenceAttemptStatus.DISPATCHING},
            ClaimEvidenceAttemptStatus.FAILED: {
                ClaimEvidenceAttemptStatus.DISPATCHING, ClaimEvidenceAttemptStatus.RESERVED,
            },
            ClaimEvidenceAttemptStatus.USAGE_UNKNOWN: {
                ClaimEvidenceAttemptStatus.DISPATCHING, ClaimEvidenceAttemptStatus.RESERVED,
            },
        }
        if status not in allowed_from:
            raise PersistenceConflict("unsupported attempt settlement")
        with self._transaction():
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                raise PersistenceConflict("supplement ledger missing")
            if ledger.epoch != epoch or ledger.owner != owner:
                raise PersistenceConflict("stale supplement owner cannot settle")
            attempt = self._attempts.get(attempt_id)
            if attempt is None:
                raise PersistenceConflict("attempt reservation missing")
            if attempt.status not in allowed_from[status]:
                if attempt.status is status and attempt.known_tokens == known_tokens:
                    return replace(ledger)
                raise PersistenceConflict("attempt already settled")
            released = ledger.reserved_tokens - attempt.reserved_tokens
            self._attempts[attempt_id] = attempt.model_copy(update={
                "status": status, "known_tokens": known_tokens,
                "unknown_usage": (known_tokens is None
                                  and status is not ClaimEvidenceAttemptStatus.NOT_SENT),
                "ended_at": now,
            })
            if status is ClaimEvidenceAttemptStatus.NOT_SENT:
                updated = replace(
                    ledger, reserved_tokens=max(0, released),
                    revision=ledger.revision + 1,
                )
            else:
                updated = replace(
                    ledger,
                    reserved_tokens=max(0, released),
                    known_tokens=ledger.known_tokens + (known_tokens or 0),
                    unknown_tokens=ledger.unknown_tokens + (
                        attempt.reserved_tokens if known_tokens is None else 0
                    ),
                    revision=ledger.revision + 1,
                )
            self._ledgers[run_id] = updated
            batch = self._batches.get(attempt.batch_id)
            if (batch is not None and batch.status is ClaimEvidenceBatchStatus.RESERVED
                    and status is not ClaimEvidenceAttemptStatus.NOT_SENT):
                self._batches[batch.batch_id] = batch.model_copy(update={
                    "status": ClaimEvidenceBatchStatus.DISPATCHED, "updated_at": now,
                })
            return replace(updated)

    def interrupt_runs(self, run_ids, *, now, reason_code="run_interrupted") -> int:
        ids = [item for item in dict.fromkeys(run_ids) if item]
        if not ids:
            return 0
        in_flight = {
            ClaimEvidenceRetrievalStatus.PENDING, ClaimEvidenceRetrievalStatus.QUERYING,
            ClaimEvidenceRetrievalStatus.RETRIEVING, ClaimEvidenceRetrievalStatus.REJUDGING,
        }
        with self._transaction():
            sessions = [
                item for item in self._sessions.values()
                if item.run_id in ids and item.status in in_flight
            ]
            if not sessions:
                return 0
            session_runs = {item.session_id: item.run_id for item in sessions}
            for attempt_id, attempt in list(self._attempts.items()):
                if attempt.status not in {
                    ClaimEvidenceAttemptStatus.RESERVED, ClaimEvidenceAttemptStatus.DISPATCHING,
                }:
                    continue
                batch = self._batches.get(attempt.batch_id)
                if batch is None or batch.session_id not in session_runs:
                    continue
                ledger = self._ledgers.get(session_runs[batch.session_id])
                if ledger is None:
                    continue
                reserved = max(0, ledger.reserved_tokens - attempt.reserved_tokens)
                if attempt.status is ClaimEvidenceAttemptStatus.DISPATCHING:
                    self._attempts[attempt_id] = attempt.model_copy(update={
                        "status": ClaimEvidenceAttemptStatus.USAGE_UNKNOWN,
                        "unknown_usage": True, "ended_at": now,
                    })
                    updated = replace(
                        ledger, reserved_tokens=reserved,
                        unknown_tokens=ledger.unknown_tokens + attempt.reserved_tokens,
                        revision=ledger.revision + 1,
                    )
                else:
                    self._attempts[attempt_id] = attempt.model_copy(update={
                        "status": ClaimEvidenceAttemptStatus.NOT_SENT,
                        "unknown_usage": False, "ended_at": now,
                    })
                    updated = replace(
                        ledger, reserved_tokens=reserved, revision=ledger.revision + 1,
                    )
                self._ledgers[session_runs[batch.session_id]] = updated
                if batch.status in {ClaimEvidenceBatchStatus.RESERVED, ClaimEvidenceBatchStatus.DISPATCHED}:
                    self._batches[batch.batch_id] = batch.model_copy(update={
                        "status": ClaimEvidenceBatchStatus.INTERRUPTED, "updated_at": now,
                    })
            for session in sessions:
                self._sessions[session.session_id] = session.model_copy(update={
                    "status": ClaimEvidenceRetrievalStatus.INTERRUPTED,
                    "reason_code": reason_code, "completed_at": now, "updated_at": now,
                })
            return len(sessions)

    def count_logical_call(self, *, run_id, owner, epoch, now) -> SupplementRunLedger:
        with self._transaction():
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                raise PersistenceConflict("supplement ledger missing")
            if ledger.owner != owner or ledger.epoch != epoch:
                raise PersistenceConflict("stale supplement owner cannot start a call")
            if ledger.logical_calls + 1 > ledger.policy.max_logical_calls:
                raise SupplementBudgetExceeded("supplement logical call budget exhausted")
            updated = replace(
                ledger, logical_calls=ledger.logical_calls + 1,
                revision=ledger.revision + 1,
            )
            self._ledgers[run_id] = updated
            return replace(updated)

    def record_query_count(self, *, run_id, count) -> SupplementRunLedger:
        with self._transaction():
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                raise PersistenceConflict("supplement ledger missing")
            total = ledger.query_count + count
            if total > ledger.policy.max_queries:
                raise SupplementBudgetExceeded("supplement query budget exhausted")
            updated = replace(ledger, query_count=total, revision=ledger.revision + 1)
            self._ledgers[run_id] = updated
            return replace(updated)

    def touch_run(self, *, run_id, status, owner, epoch) -> None:
        with self._transaction():
            ledger = self._ledgers.get(run_id)
            if ledger is None:
                return
            if ledger.epoch != epoch or ledger.owner != owner:
                raise PersistenceConflict("stale supplement owner cannot update the ledger")
            self._ledgers[run_id] = replace(ledger, status=status)

    # ---- sessions ---------------------------------------------------
    def get_session(self, session_id: str):
        with self._transaction():
            item = self._sessions.get(session_id)
            return item.model_copy(deep=True) if item is not None else None

    def find_session(self, *, run_id, resource_id, resource_version, review_id):
        with self._transaction():
            for item in self._sessions.values():
                if (
                    item.run_id == run_id and item.resource_id == resource_id
                    and item.resource_version == resource_version and item.review_id == review_id
                ):
                    return item.model_copy(deep=True)
            return None

    def create_session(self, session):
        with self._publication_transaction():
            self._assert_owned(session.run_id)
            existing = self._sessions.get(session.session_id)
            if existing is not None:
                return existing.model_copy(deep=True)
            for item in self._sessions.values():
                if (
                    item.run_id == session.run_id and item.resource_id == session.resource_id
                    and item.resource_version == session.resource_version
                    and item.review_id == session.review_id
                ):
                    raise PersistenceConflict("a supplement session already exists for this version")
            self._sessions[session.session_id] = session.model_copy(deep=True)
            from app.db.claim.publication import publication_barrier_reason

            if publication_barrier_reason(status=session.status, hard_block=session.hard_block):
                self.revoke_publication(
                    run_id=session.run_id, resource_id=session.resource_id,
                    resource_version=session.resource_version,
                )
            return session.model_copy(deep=True)

    def update_session(self, session_id, *, expected_status, status, reason_code=None,
                       query_count=None, evidence_scope_ids=None, hard_block_reason=None, now=None):
        with self._transaction():
            current = self._sessions.get(session_id)
            if current is None:
                raise PersistenceConflict("supplement session missing")
            if current.status is not expected_status:
                if current.status is status:
                    return current.model_copy(deep=True)
                raise PersistenceConflict("session CAS mismatch")
            self._check_terminal(current.status, status)
            stamped = now or datetime.now(timezone.utc)
            update: dict[str, Any] = {
                "status": status, "reason_code": reason_code, "updated_at": stamped,
            }
            if query_count is not None:
                update["query_count"] = query_count
            if evidence_scope_ids is not None:
                update["evidence_scope_ids"] = list(evidence_scope_ids)
            if hard_block_reason is not None:
                update["hard_block"] = True
                update["hard_block_reason"] = hard_block_reason
            if status in TERMINAL_STATUSES:
                update["completed_at"] = stamped
            updated = current.model_copy(update=update)
            self._sessions[session_id] = updated
            return updated.model_copy(deep=True)

    # ---- batches ----------------------------------------------------
    def save_batch(self, batch):
        with self._transaction():
            self._check_payload(batch.payload)
            existing = self._batches.get(batch.batch_id)
            if existing is not None:
                if existing.input_hash != batch.input_hash or existing.kind != batch.kind:
                    raise PersistenceConflict("batch identity payload conflict")
                if batch.kind is ClaimEvidenceBatchKind.QUERY and batch.status is ClaimEvidenceBatchStatus.COMPLETED:
                    if existing.status is ClaimEvidenceBatchStatus.COMPLETED:
                        if existing.output_hash != batch.output_hash:
                            raise PersistenceConflict("completed query batch differs")
                    else:
                        self._check_transition(existing.status.value, batch.status.value)
                        self._batches[batch.batch_id] = batch.model_copy(deep=True)
                        return batch.model_copy(deep=True)
                return existing.model_copy(deep=True)
            self._batches[batch.batch_id] = batch.model_copy(deep=True)
            return batch.model_copy(deep=True)

    def get_batch(self, batch_id: str):
        with self._transaction():
            item = self._batches.get(batch_id)
            return item.model_copy(deep=True) if item is not None else None

    def list_batches(self, session_id: str):
        with self._transaction():
            items = [item for item in self._batches.values() if item.session_id == session_id]
            return [item.model_copy(deep=True) for item in sorted(
                items, key=lambda value: (value.kind.value, value.ordinal),
            )]

    def complete_retrieval_batch(self, *, batch_id, run_id, step_id, owner, epoch,
                                 output_hash, payload, evidence, now) -> None:
        with self._transaction():
            self._assert_owned(run_id)
            self._check_payload(payload)
            batch = self._batches.get(batch_id)
            if batch is None:
                raise PersistenceConflict("retrieval batch missing")
            if batch.status is ClaimEvidenceBatchStatus.COMPLETED:
                if batch.output_hash != output_hash:
                    raise PersistenceConflict("completed retrieval batch differs")
                return
            ledger = self._ledgers.get(run_id)
            if ledger is None or ledger.owner != owner or ledger.epoch != epoch:
                raise PersistenceConflict("stale supplement owner cannot append evidence")
            knowledge_base_id = None
            if self.audit_repository is not None:
                run = self.audit_repository.get_run(run_id)
                knowledge_base_id = run.knowledge_base_id if run is not None else None
            _validate_append(
                run_id=run_id, step_id=step_id,
                knowledge_base_id=knowledge_base_id, evidence=evidence,
            )
            self.audit_repository.append_step_evidence(
                run_id=run_id, step_id=step_id, evidence=evidence, now=now,
            )
            self._check_transition(batch.status.value, ClaimEvidenceBatchStatus.COMPLETED.value)
            self._batches[batch_id] = batch.model_copy(update={
                "status": ClaimEvidenceBatchStatus.COMPLETED,
                "output_hash": output_hash, "payload": copy.deepcopy(payload),
                "updated_at": now,
            })

    @contextmanager
    def _publication_transaction(self):
        """Resource lock first, then audit→supplement, matching the reader order."""

        resource_repository = getattr(self, "resource_repository", None)
        lock = getattr(resource_repository, "_lock", None)
        if lock is None:
            with self._transaction():
                yield
            return
        with lock:
            with self._transaction():
                yield

    def save_rejudge_batch(self, *, batch_id, output_hash, payload, supplements,
                           hard_block_reason, now) -> None:
        with self._publication_transaction():
            self._check_payload(payload)
            batch = self._batches.get(batch_id)
            if batch is None:
                raise PersistenceConflict("rejudge batch missing")
            bound_session = self._sessions.get(batch.session_id)
            if bound_session is None:
                raise PersistenceConflict("supplement session missing")
            self._assert_owned(bound_session.run_id)
            if batch.status is ClaimEvidenceBatchStatus.COMPLETED:
                if batch.output_hash != output_hash:
                    raise PersistenceConflict("completed rejudge batch differs")
                return
            expected = set(batch.expected_claim_ids)
            if {item.claim_id for item in supplements} != expected:
                raise PersistenceConflict("rejudge batch does not cover its expected claims")
            available = {item.evidence_id for item in self.audit_repository.list_evidence(
                supplements[0].run_id if supplements else "",
            )} if self.audit_repository is not None else set()
            for item in supplements:
                referenced = set(item.evidence_ids) | set(item.conflicting_evidence_ids)
                if referenced - available:
                    raise PersistenceConflict("supplement judgement references missing evidence")
                existing = self._supplements.get(item.judgement_id)
                if existing is not None:
                    if existing.payload_hash != item.payload_hash:
                        raise PersistenceConflict("supplement judgement payload conflict")
                    continue
                self._supplements[item.judgement_id] = item.model_copy(deep=True)
            if hard_block_reason is not None:
                session = self._sessions.get(batch.session_id)
                if session is None:
                    raise PersistenceConflict("supplement session missing")
                self._sessions[batch.session_id] = session.model_copy(update={
                    "hard_block": True, "hard_block_reason": hard_block_reason,
                    "updated_at": now,
                })
                # Version-level safety stamp in the same critical section.
                self.revoke_publication(
                    run_id=session.run_id, resource_id=session.resource_id,
                    resource_version=session.resource_version,
                )
            self._check_transition(batch.status.value, ClaimEvidenceBatchStatus.COMPLETED.value)
            self._batches[batch_id] = batch.model_copy(update={
                "status": ClaimEvidenceBatchStatus.COMPLETED,
                "output_hash": output_hash, "payload": copy.deepcopy(payload),
                "updated_at": now,
            })

    # ---- scopes and activation --------------------------------------
    def _upsert_scope_memory(self, scope):
        existing = self._scopes.get(scope.scope_id)
        if existing is not None:
            if existing.manifest_hash != scope.manifest_hash:
                raise PersistenceConflict("evidence scope payload conflict")
            return existing
        for item in self._scopes.values():
            if (
                item.run_id == scope.run_id
                and item.resource_id == scope.resource_id
                and item.resource_version == scope.resource_version
                and item.purpose == scope.purpose
                and item.session_id == scope.session_id
            ):
                raise PersistenceConflict("evidence scope identity conflict")
        stored = scope.model_copy(deep=True)
        self._scopes[scope.scope_id] = stored
        return stored

    def save_evidence_set(self, scope):
        with self._transaction():
            self._assert_owned(scope.run_id)
            return self._upsert_scope_memory(scope).model_copy(deep=True)

    def list_evidence_sets(self, run_ids):
        ids = set(run_ids)
        with self._transaction():
            items = [item for item in self._scopes.values() if item.run_id in ids]
            return [item.model_copy(deep=True) for item in sorted(
                items, key=lambda value: (value.run_id, value.resource_id, value.resource_version),
            )]

    def activate_session(self, *, session_id, scope, round_one_hash, supported,
                         contradicted, absent, factual, claim_total, now):
        with self._transaction():
            current = self._sessions.get(session_id)
            if current is None:
                raise PersistenceConflict("supplement session missing")
            self._assert_owned(current.run_id)
            self._check_round_one(
                target_claim_ids=current.target_claim_ids,
                persisted=[
                    {
                        "claim_id": item.claim_id,
                        "judgement_id": item.judgement_id,
                        "status": item.status.value,
                        "verdict": item.verdict.value if item.verdict is not None else None,
                    }
                    for item in self._supplements.values()
                    if item.session_id == session_id
                ],
                round_one_hash=round_one_hash,
            )
            if current.active:
                return current.model_copy(deep=True)
            self._check_terminal(current.status, ClaimEvidenceRetrievalStatus.COMPLETED)
            for item in self._sessions.values():
                if (
                    item.session_id != session_id and item.active
                    and item.run_id == current.run_id
                    and item.resource_id == current.resource_id
                    and item.resource_version == current.resource_version
                    and item.review_id == current.review_id
                ):
                    raise PersistenceConflict("another session is already active")
            self._upsert_scope_memory(scope)
            updated = current.model_copy(update={
                "status": ClaimEvidenceRetrievalStatus.COMPLETED,
                "active": True, "updated_at": now, "completed_at": now,
                "evidence_scope_ids": list(dict.fromkeys(
                    [*current.evidence_scope_ids, scope.scope_id]
                )),
            })
            self._sessions[session_id] = updated
            if self.audit_repository is not None:
                self.audit_repository.update_claim_metrics(
                    review_id=current.review_id,
                    claim_total=claim_total,
                    supported=supported,
                    contradicted=contradicted,
                    absent=absent,
                    factual=factual,
                )
            return updated.model_copy(deep=True)

    def list_sessions(self, run_ids):
        ids = set(run_ids)
        with self._transaction():
            items = [item for item in self._sessions.values() if item.run_id in ids]
            return [item.model_copy(deep=True) for item in sorted(
                items, key=lambda value: (value.run_id, value.resource_id, value.resource_version),
            )]

    def list_supplements(self, run_ids):
        ids = set(run_ids)
        with self._transaction():
            items = [item for item in self._supplements.values() if item.run_id in ids]
            return [item.model_copy(deep=True) for item in sorted(
                items, key=lambda value: (
                    value.run_id, value.resource_id, value.resource_version, value.claim_id,
                ),
            )]

    def list_history(self, run_id: str):
        return (
            self.list_sessions([run_id]),
            self.list_supplements([run_id]),
            self.list_evidence_sets([run_id]),
        )

    # ---- publication guard ------------------------------------------
    def publication_barrier(
        self, run_id: str, resource_id: str, resource_version: int,
    ) -> str | None:
        """Durable lookup shared with the resource repository write path."""

        from app.db.claim.publication import barrier_reason_for_sessions

        with self._transaction():
            bound = [
                item for item in self._sessions.values()
                if item.run_id == run_id
                and item.resource_id == resource_id
                and item.resource_version == int(resource_version)
            ]
            return barrier_reason_for_sessions(bound)

    def revoke_publication(
        self, *, run_id: str, resource_id: str, resource_version: int,
    ) -> bool:
        """Memory counterpart of the SQL version-level safety stamp."""

        repository = getattr(self, "resource_repository", None)
        if repository is None:
            return False
        return repository.revoke_publication(
            run_id=run_id, resource_id=resource_id,
            resource_version=resource_version,
        )

def create_supplement_repository(*, claim_repository, audit_repository, resource_repository=None):
    from app.db.claim.memory import MemoryClaimRepository
    from app.db.claim.sql_repository import SQLClaimRepository

    if isinstance(claim_repository, MemoryClaimRepository):
        repository = MemoryClaimSupplementRepository(
            claim_repository=claim_repository, audit_repository=audit_repository,
        )
        if resource_repository is not None:
            from app.db.claim.publication import bind_memory_publication_guard

            bind_memory_publication_guard(resource_repository, repository)
        return repository
    if isinstance(claim_repository, SQLClaimRepository):
        return SQLClaimSupplementRepository(
            claim_repository=claim_repository,
            audit_repository=audit_repository,
            session_factory=claim_repository.session_factory,
        )
    raise ValueError(f"unsupported claim repository: {type(claim_repository).__name__}")


__all__ = [
    "BaseClaimSupplementRepository",
    "MemoryClaimSupplementRepository",
    "SQLClaimSupplementRepository",
    "SupplementBudgetExceeded",
    "SupplementRunLedger",
    "SupplementSessionClosed",
    "create_supplement_repository",
    "utc",
]
