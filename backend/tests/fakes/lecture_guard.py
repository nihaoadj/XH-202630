"""Shared helper to stand up a legal durable review entry for V2 tests.

Production requires a recorded review step plus a fenced owner and a live lease
before any V2 request can be sent.  These helpers set up a Memory repository
with those preconditions and return a ready ``step_guard`` callable plus the
context manager that keeps the execution fence active while the engine runs.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from app.core.execution import ExecutionFence, execution_fence
from app.db.audit.memory import MemoryAuditRepository
from app.models.shared.persistence import (
    BeginStepCommand,
    CreateRunCommand,
    canonical_hash,
)

from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
    assert_review_entry_allowed,
)


def legal_review_entry(*, run_id: str = "run-review-test", step_id: str = "review-step",
                       owner: str = "owner-1", lease_seconds: int = 3600):
    """Create a Memory repository with a running review step, owner and live lease."""
    repo = MemoryAuditRepository()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=lease_seconds)
    repo.create_run(CreateRunCommand(
        run_id=run_id, request_snapshot={}, request_hash=canonical_hash({}),
        owner_instance_id=owner, lease_expires_at=expires, occurred_at=now))
    repo.start_run(run_id, occurred_at=now, lease_expires_at=expires)
    repo.begin_step(BeginStepCommand(
        run_id=run_id, step_id=step_id, step_sequence=1, node_name="reviewer",
        agent_name="reviewer", action="review", generation_attempt=1,
        started_at=now, lease_expires_at=expires))
    return repo, run_id, step_id, owner


def step_guard_factory(repository, *, run_id: str, owner: str):
    """Return the durable ``step_guard`` callable the engine requires."""

    def guard(*, step_id, generation_attempt):
        assert_review_entry_allowed(
            repository=repository, run_id=run_id, step_id=step_id,
            generation_attempt=generation_attempt)

    return guard


@contextmanager
def fenced(run_id: str, owner: str):
    """Activate the ambient execution fence for the duration of the block."""
    with execution_fence(ExecutionFence(run_id=run_id, owner=owner)):
        yield
