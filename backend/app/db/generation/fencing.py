"""Validate execution ownership in the transaction that commits its effects."""
from datetime import datetime, timezone

from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.core.execution import current_execution_fence
from app.db.audit.base import PersistenceConflict
from app.db.shared.models import AgentRunORM, GenerationJobORM


class ExecutionLeaseLost(PersistenceConflict):
    def __init__(self):
        super().__init__("GENERATION_EXECUTION_LEASE_LOST")


def _guard_commit(session: Session, *_) -> None:
    fence = current_execution_fence()
    if fence is None:
        return
    transaction = session.get_transaction()
    if session.info.get("generation_fence_transaction") == (fence, transaction):
        # A successful guard holds the writer lock for this transaction. The
        # same transaction may now flush its own terminal run transition.
        return
    now = datetime.now(timezone.utc)
    connection = session.connection()
    if fence.epoch is not None:
        statement = update(GenerationJobORM).where(
            GenerationJobORM.run_id == fence.run_id,
            GenerationJobORM.status == "running",
            GenerationJobORM.claim_owner == fence.owner,
            GenerationJobORM.claim_epoch == fence.epoch,
            GenerationJobORM.lease_expires_at > now,
        ).values(claim_epoch=GenerationJobORM.claim_epoch)
    else:
        # The first run insert has not flushed yet. Only its own identity may create it.
        pending = [row for row in session.new if isinstance(row, AgentRunORM) and row.run_id == fence.run_id]
        if pending and pending[0].owner_instance_id == fence.owner:
            return
        statement = update(AgentRunORM).where(
            AgentRunORM.run_id == fence.run_id,
            AgentRunORM.owner_instance_id == fence.owner,
            AgentRunORM.status.in_(("created", "running", "finalizing")),
            AgentRunORM.lease_expires_at > now,
        ).values(row_version=AgentRunORM.row_version)
    # The UPDATE also holds the SQLite writer lock through the effects' commit.
    if connection.execute(statement).rowcount != 1:
        raise ExecutionLeaseLost()
    if fence.epoch is not None:
        stored = connection.execute(AgentRunORM.__table__.select().where(AgentRunORM.run_id == fence.run_id)).mappings().first()
        if stored and (stored["status"] not in {"created", "running", "finalizing"}
                       or stored["owner_instance_id"] != fence.owner
                       or stored["lease_expires_at"] is None
                       or stored["lease_expires_at"].replace(tzinfo=timezone.utc) <= now):
            raise ExecutionLeaseLost()
    session.info["generation_fence_transaction"] = (fence, session.get_transaction())


def install_execution_fencing() -> None:
    if not event.contains(Session, "before_commit", _guard_commit):
        event.listen(Session, "before_commit", _guard_commit)
        event.listen(Session, "before_flush", _guard_commit)
