"""One persistent publication guard shared by every release path.

The guard is deliberately not a workflow-level list: automatic finalization, the
user decision endpoint, replay of a publication event and a direct repository
call all resolve the same durable facts inside their own write transaction.

* an in-flight round (``pending``/``querying``/``retrieving``/``rejudging``) is a
  temporary barrier for that resource version;
* an ``interrupted`` round keeps the barrier: the version stays unpublished and
  the user cannot clear it by confirming;
* a persisted round-1 counter-evidence or source conflict is a permanent block
  for that version; only a new child version can be published again.

No model or retrieval call happens here, and nothing in this module mutates a
session or judgement row.
"""

from __future__ import annotations

from app.db.audit.base import PersistenceConflict
from app.models.reviews.claim_evidence_retrieval import (
    ACTIVE_STATUSES,
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
)

IN_FLIGHT_REASON = "claim_evidence_in_flight"
INTERRUPTED_REASON = "claim_evidence_interrupted"
HARD_BLOCK_REASON = "claim_evidence_hard_block"
BARRIER_REASONS = frozenset({IN_FLIGHT_REASON, INTERRUPTED_REASON, HARD_BLOCK_REASON})


class PublicationBarrier(PersistenceConflict):
    """A resource version may not be published in its current evidence state."""

    def __init__(self, reason_code: str) -> None:
        if reason_code not in BARRIER_REASONS:
            raise ValueError(f"unknown publication barrier reason: {reason_code}")
        super().__init__(f"resource publication blocked by {reason_code}")
        self.reason_code = reason_code


def publication_barrier_reason(
    *,
    status: str | ClaimEvidenceRetrievalStatus | None,
    hard_block: bool,
) -> str | None:
    """Pure barrier decision for one stored session row."""

    if hard_block:
        return HARD_BLOCK_REASON
    if status is None:
        return None
    try:
        value = ClaimEvidenceRetrievalStatus(status)
    except ValueError:
        # An unknown stored status fails closed: the writer cannot prove the
        # round is finished, so publishing stays blocked.
        return IN_FLIGHT_REASON
    if value in ACTIVE_STATUSES:
        return IN_FLIGHT_REASON
    if value is ClaimEvidenceRetrievalStatus.INTERRUPTED:
        return INTERRUPTED_REASON
    return None


def barrier_reason_for_sessions(
    sessions: list[ClaimEvidenceRetrievalSessionV1],
) -> str | None:
    """First blocking reason across every session bound to one version."""

    return _combine([
        publication_barrier_reason(status=item.status, hard_block=item.hard_block)
        for item in sessions
    ])


def assert_publication_allowed(reason: str | None) -> None:
    if reason is not None:
        raise PublicationBarrier(reason)


# ---- SQL helpers (caller owns the transaction) ---------------------------
def lock_sql_resource(db, resource_id: str) -> None:
    """Serialize publication and supplement creation before either reads state.

    UPDATE takes a writer lock on SQLite as well as a row lock on PostgreSQL;
    SELECT FOR UPDATE alone does not provide that guarantee on SQLite.
    """
    from sqlalchemy import update
    from app.db.shared.models import GeneratedResourceORM
    from app.core.execution import current_execution_fence
    from app.db.generation.fencing import assert_execution_ownership

    fence = current_execution_fence()
    if fence is not None:
        assert_execution_ownership(db, fence.run_id)
    db.execute(update(GeneratedResourceORM).where(
        GeneratedResourceORM.resource_id == resource_id,
    ).values(version=GeneratedResourceORM.version))


def sql_barrier_reason(
    db,
    *,
    run_id: str | None,
    resource_id: str,
    resource_version: int,
) -> str | None:
    """Resolve the barrier from persisted rows on the caller's connection."""

    from app.db.claim.supplement_models import ClaimEvidenceRetrievalSessionORM

    if not run_id:
        return None
    rows = (
        db.query(ClaimEvidenceRetrievalSessionORM)
        .filter_by(
            run_id=run_id, resource_id=resource_id,
            resource_version=int(resource_version),
        )
        .all()
    )
    return _combine([
        publication_barrier_reason(status=row.status, hard_block=bool(row.hard_block))
        for row in rows
    ])


def assert_sql_publication_allowed(
    db, *, run_id: str | None, resource_id: str, resource_version: int,
) -> None:
    assert_publication_allowed(
        sql_barrier_reason(
            db, run_id=run_id, resource_id=resource_id,
            resource_version=resource_version,
        )
    )


def revoke_sql_publication(
    db, *, run_id: str | None, resource_id: str, resource_version: int,
) -> bool:
    """Version-level safety stamp written in the counter-evidence transaction.

    A publication that already committed before the new contradiction is
    withdrawn here, so the persisted state can never show a published version
    together with a hard block.
    """

    from app.db.shared.models import GeneratedResourceORM

    if not run_id:
        return False
    row = (
        db.query(GeneratedResourceORM)
        .filter_by(resource_id=resource_id, run_id=run_id, version=int(resource_version))
        .with_for_update()
        .first()
    )
    if row is None:
        return False
    row.publication_status = "unpublished"
    row.published_at = None
    row.claim_publish_decision_pending = False
    row.claim_publish_decision = None
    return True


def _combine(reasons: list[str | None]) -> str | None:
    present = {item for item in reasons if item is not None}
    if not present:
        return None
    for preferred in (HARD_BLOCK_REASON, INTERRUPTED_REASON, IN_FLIGHT_REASON):
        if preferred in present:
            return preferred
    return sorted(present)[0]


def bind_memory_publication_guard(resource_repository, supplement_repository) -> None:
    """Wire the two memory repositories without a constructor cycle.

    The resource repository asks the supplement repository for the durable
    barrier, and the supplement repository asks the resource repository to
    withdraw an already published version when a counter-evidence batch
    commits.  Both references are set after construction, so neither provider
    depends on the other while being built.
    """

    if resource_repository is None or supplement_repository is None:
        return
    if hasattr(resource_repository, "publication_guard"):
        resource_repository.publication_guard = supplement_repository.publication_barrier
    if hasattr(supplement_repository, "resource_repository"):
        supplement_repository.resource_repository = resource_repository


def barrier_stamp_payload(reason_code: str, *, resource_id: str, resource_version: int) -> dict:
    """Bounded event payload for an observable barrier decision."""

    return {
        "resource_id": resource_id,
        "resource_version": int(resource_version),
        "barrier": reason_code,
    }


__all__ = [
    "BARRIER_REASONS",
    "HARD_BLOCK_REASON",
    "IN_FLIGHT_REASON",
    "INTERRUPTED_REASON",
    "PublicationBarrier",
    "assert_publication_allowed",
    "assert_sql_publication_allowed",
    "barrier_reason_for_sessions",
    "barrier_stamp_payload",
    "bind_memory_publication_guard",
    "publication_barrier_reason",
    "revoke_sql_publication",
    "sql_barrier_reason",
]
