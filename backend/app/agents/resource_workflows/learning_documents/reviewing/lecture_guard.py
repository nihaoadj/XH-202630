"""Persistent entry guard for V2 lecture review.

The repository ``begin_step`` row is committed before the node body runs, so it
already records "this review step may have sent a request".  If that step never
reaches a verifiable terminal state, the run must not silently start a new
review with a fresh attempt budget.  We therefore refuse entry whenever the run
carries an unfinished review step, or a finished one without its audit and
checkpoint reference.

Ownership and lease are also enforced here.  The caller is never trusted to
self-report its owner: ownership comes from the ambient ``ExecutionFence``
context (``current_execution_fence``), which is the same identity the
persistence layer uses to fence the commit of effects.  A worker whose lease
has expired, or which no longer holds ownership of the run, is refused before
it can send the first or the correction request.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.core.execution import current_execution_fence
from app.db.audit.base import BaseAuditRepository

REVIEW_NODE_NAMES = frozenset({"review", "reviewer"})
TERMINAL_REVIEW_STATUSES = frozenset({"success", "degraded", "human_review"})


class LectureStepGuardError(ValueError):
    """The run cannot safely start another lecture review request."""

    def __init__(self, reason: str, detail: str = ""):
        self.reason = reason
        super().__init__(f"lecture review entry blocked: {reason}{': ' + detail if detail else ''}")


def _checkpoint_for(checkpoints, step_id: str):
    return [item for item in checkpoints if item.step_id == step_id]


def _assert_owner_and_lease(*, repository: BaseAuditRepository, run_id: str) -> None:
    """Enforce execution ownership and a live lease from the ambient fence.

    Ownership may only come from ``current_execution_fence``; the caller cannot
    pass an owner it asserts about itself.  When no fence is active (a helper
    or a reduced script context) we refuse, because a real sendable entry must
    always run inside a fenced execution.
    """
    fence = current_execution_fence()
    if fence is None:
        raise LectureStepGuardError("execution_fence_missing")
    if fence.run_id != run_id:
        raise LectureStepGuardError("execution_fence_run_mismatch", fence.run_id)
    run = repository.get_run(run_id)
    if run is None:
        raise LectureStepGuardError("run_not_found", run_id)
    if run.owner_instance_id is None:
        raise LectureStepGuardError("run_owner_missing", run_id)
    if run.owner_instance_id != fence.owner:
        raise LectureStepGuardError("run_owner_mismatch", run.owner_instance_id)
    # Dispatch epochs count job acquisitions; run.row_version counts writes.
    # Only the durable dispatch ledger can establish whether this epoch is live.
    if fence.epoch is not None:
        try:
            repository.validate_review_execution_epoch(run_id, fence.owner, fence.epoch)
        except Exception as exc:
            raise LectureStepGuardError("run_epoch_mismatch") from exc
    lease = run.lease_expires_at
    if lease is None:
        raise LectureStepGuardError("run_lease_missing", run_id)
    if lease.astimezone(timezone.utc) <= datetime.now(timezone.utc):
        raise LectureStepGuardError("run_lease_expired", lease.isoformat())


def assert_review_entry_allowed(*, repository: BaseAuditRepository | None, run_id: str,
                                step_id: str, generation_attempt: int,
                                node_name: str = "reviewer") -> None:
    """Raise unless this step is the run's only live review execution.

    ``repository is None`` means a reduced helper context without durable
    storage; callers that can send real requests must pass a repository, and
    a missing repository is therefore a hard failure here.
    """
    if repository is None:
        raise LectureStepGuardError("durable_repository_missing")
    _assert_owner_and_lease(repository=repository, run_id=run_id)
    steps = list(repository.list_steps(run_id))
    current = [item for item in steps if item.step_id == step_id]
    if len(current) != 1:
        raise LectureStepGuardError("review_step_not_recorded", step_id)
    record = current[0]
    if record.node_name not in REVIEW_NODE_NAMES:
        raise LectureStepGuardError("review_step_node_mismatch", record.node_name)
    if record.generation_attempt != generation_attempt:
        raise LectureStepGuardError("review_step_attempt_mismatch", str(record.generation_attempt))
    if record.status not in {"running", "started"}:
        raise LectureStepGuardError("review_step_not_running", record.status)

    checkpoints = list(repository.list_checkpoints(run_id))
    for item in steps:
        if item.step_id == step_id or item.node_name not in REVIEW_NODE_NAMES:
            continue
        if item.step_sequence > record.step_sequence:
            continue
        if item.status not in TERMINAL_REVIEW_STATUSES:
            raise LectureStepGuardError("previous_review_step_unfinished", item.step_id)
        audit = repository.get_step_review_audit(run_id, item.step_id)
        if audit is None:
            raise LectureStepGuardError("previous_review_audit_missing", item.step_id)
        if not _checkpoint_for(checkpoints, item.step_id):
            raise LectureStepGuardError("previous_review_checkpoint_missing", item.step_id)


def assert_no_unfinished_review(*, repository: BaseAuditRepository | None, run_id: str) -> None:
    """Runner-side variant: refuse to resume a run holding an unfinished review."""
    if repository is None:
        return
    steps = list(repository.list_steps(run_id))
    checkpoints = list(repository.list_checkpoints(run_id))
    for item in steps:
        if item.node_name not in REVIEW_NODE_NAMES:
            continue
        if item.status in TERMINAL_REVIEW_STATUSES:
            audit = repository.get_step_review_audit(run_id, item.step_id)
            if audit is None or not _checkpoint_for(checkpoints, item.step_id):
                raise LectureStepGuardError("previous_review_chain_incomplete", item.step_id)
            continue
        raise LectureStepGuardError("previous_review_step_unfinished", item.step_id)
