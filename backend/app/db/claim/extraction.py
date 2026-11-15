"""Private SQL/explicit Memory CAS, sharing the audit creation transaction."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone, timedelta
import math

from sqlalchemy import update

from app.core.execution import current_execution_fence
from app.db.audit.base import PersistenceConflict, PersistenceError
from app.db.shared.models import AgentRunORM, ClaimExtractionRunORM, GenerationJobORM
from app.models.reviews.claim_extraction import (
    LEGACY, NEUTRAL, ESTIMATE, EstimateLedger, ExtractionLedger, LedgerSnapshot, check_ledger_size, digest,
    policy_from_input, validate_snapshot,
    validate_transition,
)


def utc(value):
    return value.replace(tzinfo=timezone.utc) if value and value.tzinfo is None else value


def creation_snapshot(run_id, payload):
    policy = policy_from_input(payload)
    if policy is None:
        return None
    state = EstimateLedger() if policy.strategy == ESTIMATE else ExtractionLedger()
    check_ledger_size(policy, state)
    return LedgerSnapshot(run_id=run_id, policy=policy, policy_hash=digest(policy), revision=0,
                          state_hash=digest(state), state=state)


def add_sql_creation(db, run, payload):
    snapshot = creation_snapshot(run.run_id, payload)
    run.claim_extraction_mode = snapshot.policy.strategy if snapshot else LEGACY
    if snapshot:
        db.add(ClaimExtractionRunORM(run_id=run.run_id, schema_version=snapshot.policy.schema_version, policy_hash=snapshot.policy_hash,
            policy_json=snapshot.policy.model_dump(mode="json"), revision=0,
            state_hash=snapshot.state_hash, state_json=snapshot.state.model_dump(mode="json")))


def read_sql(db, run):
    row = db.get(ClaimExtractionRunORM, run.run_id)
    if row is not None and row.schema_version not in {"1.0", "2.0"}:
        raise PersistenceError("unknown claim extraction ledger schema")
    if row is not None and (row.schema_version != row.policy_json.get("schema_version")
                            or row.schema_version != row.state_json.get("schema_version")):
        raise PersistenceError("claim extraction ledger schema mismatch")
    material = None if row is None else dict(run_id=row.run_id, policy=row.policy_json, policy_hash=row.policy_hash,
        revision=row.revision, state_hash=row.state_hash, state=row.state_json)
    try:
        return validate_snapshot(run.claim_extraction_mode, run.input_payload or {}, material)
    except ValueError as exc:
        raise PersistenceError("claim extraction durable state invalid") from exc


def _owned_state(old, new_state, *, owner, session_id, epoch, deadline, now):
    if not owner or not session_id or deadline is None or utc(deadline) <= now:
        raise PersistenceConflict("claim extraction execution expired")
    if old.active_owner is not None:
        if (old.active_owner != owner or old.execution_session_id != session_id or old.fence_epoch != epoch
                or old.session_closed or old.owner_deadline_at is None or utc(old.owner_deadline_at) <= now):
            raise PersistenceConflict("claim extraction interrupted or busy")
        if new_state.ledger_epoch != old.ledger_epoch:
            raise PersistenceConflict("claim extraction epoch mismatch")
    elif new_state.ledger_epoch != 1:
        raise PersistenceConflict("claim extraction initial epoch mismatch")
    if (new_state.active_owner != owner or new_state.execution_session_id != session_id
            or new_state.fence_epoch != epoch):
        raise PersistenceConflict("claim extraction owner mismatch")
    validate_transition(old, new_state)
    return new_state.model_copy(update={"owner_deadline_at": utc(deadline)})


def _reservation_seconds(current, new_state, requested):
    if not math.isfinite(requested) or requested < 0:
        raise ValueError("invalid reservation time")
    additions = [t for k, t in new_state.tickets.items() if k not in current.state.tickets]
    if (additions or new_state.results.keys() - current.state.results.keys()) and any(t.status == "in_flight" for t in current.state.tickets.values()):
        raise PersistenceConflict("unknown extraction ticket blocks further work")
    if new_state.results.keys() - current.state.results.keys() and any(r.status == "running" for r in current.state.results.values()):
        raise PersistenceConflict("unfinished extraction result blocks further work")
    if len(additions) > 1:
        raise ValueError("extraction reservations must be serial")
    for ticket in additions:
        minimum = ticket.timeout_seconds * ticket.attempts + current.policy.backoff_seconds * max(0, ticket.attempts - 1)
        if ticket.time_ms < math.ceil(minimum * 1000):
            raise ValueError("ticket does not cover attempts and backoff")
    return max(requested, sum(t.time_ms for t in additions) / 1000)


class SQLClaimExtractionRepository:
    def __init__(self, session_factory, *, clock=lambda: datetime.now(timezone.utc)):
        self.session_factory = session_factory
        self.clock = clock

    def get(self, run_id):
        with self.session_factory() as db:
            run = db.get(AgentRunORM, run_id)
            if run is None:
                raise PersistenceError("claim extraction run missing")
            return read_sql(db, run)

    def compare_and_swap(self, snapshot, new_state, *, owner, session_id, required_seconds=0):
        # Fencing imports the audit package too. Resolve only at execution time
        # so a fresh Worker process can import its repository first.
        from app.db.generation.fencing import _guard_commit
        fence = current_execution_fence()
        if fence is None or (fence.run_id, fence.owner) != (snapshot.run_id, owner):
            raise PersistenceConflict("claim extraction requires execution fence")
        with self.session_factory() as db:
            # Ownership UPDATE takes the writer lock before leases and CAS.
            _guard_commit(db)
            run = db.get(AgentRunORM, snapshot.run_id)
            current = read_sql(db, run) if run else None
            if current is None or (current.revision, current.state_hash, current.policy_hash) != (snapshot.revision, snapshot.state_hash, snapshot.policy_hash):
                raise PersistenceConflict("claim extraction CAS conflict")
            now = self.clock()
            required_seconds = _reservation_seconds(current, new_state, required_seconds)
            deadline = utc(run.lease_expires_at)
            if run.status != "running" or run.owner_instance_id != owner:
                raise PersistenceConflict("claim extraction run is not owned and running")
            if fence.epoch is not None:
                job = db.query(GenerationJobORM).filter_by(run_id=snapshot.run_id).one_or_none()
                if not job or job.status != "running" or job.claim_owner != owner or job.claim_epoch != fence.epoch:
                    raise PersistenceConflict("claim extraction job fence lost")
                deadline = min(deadline, utc(job.lease_expires_at)) if deadline and job.lease_expires_at else None
            if deadline is None or deadline <= now + timedelta(seconds=required_seconds):
                raise PersistenceConflict("claim extraction lease cannot cover reservation")
            new_state = _owned_state(current.state, type(current.state).model_validate(new_state), owner=owner,
                session_id=session_id, epoch=fence.epoch, deadline=deadline, now=now)
            check_ledger_size(current.policy, new_state)
            state_hash = digest(new_state)
            validate_snapshot(current.policy.strategy, run.input_payload, current.model_copy(update={"state": new_state, "state_hash": state_hash}))
            changed = db.execute(update(ClaimExtractionRunORM).where(
                ClaimExtractionRunORM.run_id == snapshot.run_id,
                ClaimExtractionRunORM.revision == snapshot.revision,
                ClaimExtractionRunORM.state_hash == snapshot.state_hash,
            ).values(state_json=new_state.model_dump(mode="json"), state_hash=state_hash,
                     revision=snapshot.revision + 1, updated_at=now))
            if changed.rowcount != 1:
                raise PersistenceConflict("claim extraction CAS conflict")
            db.commit()
            return current.model_copy(update={"state": new_state, "state_hash": state_hash, "revision": snapshot.revision + 1})


class MemoryClaimExtractionRepository:
    """Only an explicitly supplied Memory audit owns this test/local storage."""
    def __init__(self, audit_repository, *, clock=lambda: datetime.now(timezone.utc)):
        self.audit = audit_repository
        self.clock = clock

    def get(self, run_id):
        with self.audit._lock:
            run = self.audit._require_run(run_id)
            try:
                return deepcopy(validate_snapshot(run.get("claim_extraction_mode", LEGACY), run["input_payload"], self.audit.claim_extraction_rows.get(run_id)))
            except ValueError as exc:
                raise PersistenceError("claim extraction durable state invalid") from exc

    def compare_and_swap(self, snapshot, new_state, *, owner, session_id, required_seconds=0):
        with self.audit._lock:
            current = self.get(snapshot.run_id)
            if current is None or (current.revision, current.state_hash, current.policy_hash) != (snapshot.revision, snapshot.state_hash, snapshot.policy_hash):
                raise PersistenceConflict("claim extraction CAS conflict")
            run = self.audit._require_run(snapshot.run_id)
            now = self.clock()
            required_seconds = _reservation_seconds(current, new_state, required_seconds)
            if run["status"] != "running" or run["owner_instance_id"] != owner:
                raise PersistenceConflict("claim extraction run is not owned and running")
            deadline = utc(run["lease_expires_at"])
            if not deadline or deadline <= now + timedelta(seconds=required_seconds):
                raise PersistenceConflict("claim extraction lease cannot cover reservation")
            fence = current_execution_fence()
            if fence and (fence.run_id, fence.owner) != (snapshot.run_id, owner):
                raise PersistenceConflict("claim extraction fence mismatch")
            new_state = _owned_state(current.state, type(current.state).model_validate(new_state), owner=owner,
                session_id=session_id, epoch=fence.epoch if fence else None, deadline=deadline, now=now)
            check_ledger_size(current.policy, new_state)
            result = current.model_copy(update={"state": deepcopy(new_state), "state_hash": digest(new_state), "revision": current.revision + 1})
            validate_snapshot(current.policy.strategy, run["input_payload"], result)
            self.audit.claim_extraction_rows[snapshot.run_id] = result.model_dump(mode="json")
            return deepcopy(result)


def extraction_repository(audit):
    # No implicit process-local fallback for custom/SQL production repositories.
    from app.db.audit.memory import MemoryAuditRepository
    from app.db.audit.sql_repository import SQLAuditRepository
    if isinstance(audit, SQLAuditRepository):
        return SQLClaimExtractionRepository(audit.session_factory)
    if isinstance(audit, MemoryAuditRepository):
        return MemoryClaimExtractionRepository(audit)
    return None
