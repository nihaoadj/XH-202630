from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from app.core.execution import ExecutionFence, execution_fence
from app.db.audit.base import PersistenceConflict, PersistenceError
from app.db.audit.memory import MemoryAuditRepository
from app.db.shared.models import AgentRunORM, ClaimExtractionRunORM
from app.models.reviews.claim_extraction import ExtractionLedger, ExtractionTicket, ExtractionResult, digest, result_identity_key
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from tests.fakes.claim_extraction import prepare_ledger, policy, snapshot_for
from tests.fakes.persistence import sqlite_repository


@pytest.fixture(params=["memory", "sqlite"])
def storage(request, tmp_path):
    if request.param == "memory":
        audit = MemoryAuditRepository()
        engine = None
    else:
        audit, engine = sqlite_repository(tmp_path)
    with execution_fence(ExecutionFence("run-neutral", "owner")):
        audit, repo = prepare_ledger(audit)
        yield audit, repo
    if engine:
        engine.dispose()


def owned(snapshot):
    return snapshot.state.model_copy(update=dict(active_owner="owner", execution_session_id="session",
        ledger_epoch=1, fence_epoch=None))


def test_create_atomic_deepcopy_and_cas(storage):
    audit, repo = storage
    a = repo.get("run-neutral")
    b = repo.compare_and_swap(a, owned(a), owner="owner", session_id="session", required_seconds=60)
    assert b.revision == 1 and b.state_hash == digest(b.state)
    with pytest.raises(PersistenceConflict):
        repo.compare_and_swap(a, owned(a), owner="owner", session_id="session")
    b.state.results["fake"] = {}
    assert repo.get("run-neutral").state.results == {}
    assert "claim_extraction" not in str(audit.get_run("run-neutral").model_dump())
    snap = snapshot_for(policy())
    snap["claim_extraction_policy_hash"] = "0" * 64
    with pytest.raises(ValueError):
        audit.create_run(CreateRunCommand(run_id="invalid", request_snapshot=snap, request_hash=canonical_hash(snap)))
    assert audit.get_run("invalid") is None
    if hasattr(audit, "session_factory"):
        with audit.session_factory() as db:
            assert db.get(ClaimExtractionRunORM, "invalid") is None


@pytest.mark.parametrize("loss", ["policy", "ledger", "both", "mode"])
def test_mode_detects_single_and_double_loss(storage, loss):
    audit, repo = storage
    if isinstance(audit, MemoryAuditRepository):
        if loss in {"policy", "both"}:
            audit.runs["run-neutral"]["input_payload"] = {}
        if loss in {"ledger", "both"}:
            audit.claim_extraction_rows.pop("run-neutral")
        if loss == "mode":
            audit.runs["run-neutral"]["claim_extraction_mode"] = "legacy_v3"
    else:
        with audit.session_factory() as db:
            if loss in {"policy", "both"}:
                db.get(AgentRunORM, "run-neutral").input_payload = {}
            if loss in {"ledger", "both"}:
                db.delete(db.get(ClaimExtractionRunORM, "run-neutral"))
            if loss == "mode":
                db.get(AgentRunORM, "run-neutral").claim_extraction_mode = "legacy_v3"
            db.commit()
    with pytest.raises((ValueError, PersistenceError)):
        repo.get("run-neutral")
    with pytest.raises((ValueError, PersistenceError)):
        audit.get_run("run-neutral")
    for read in (audit.list_steps, audit.list_events, audit.list_checkpoints, audit.list_evidence, audit.list_reviews_by_run):
        with pytest.raises((ValueError, PersistenceError)):
            read("run-neutral")


def test_no_late_owner_new_session_or_unfenced_sql_writes(storage):
    audit, repo = storage
    a = repo.get("run-neutral")
    a = repo.compare_and_swap(a, owned(a), owner="owner", session_id="session")
    with pytest.raises(PersistenceConflict):
        repo.compare_and_swap(a, a.state, owner="owner", session_id="new-session")
    with pytest.raises(PersistenceConflict):
        repo.compare_and_swap(a, a.state, owner="owner", session_id="session", required_seconds=2400)
    repo.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=2400)
    with pytest.raises(PersistenceConflict):
        repo.compare_and_swap(a, a.state, owner="owner", session_id="session")
    assert repo.get("run-neutral").revision == a.revision


def test_sql_requires_fence_and_concurrent_cas_has_one_winner(tmp_path):
    audit, engine = sqlite_repository(tmp_path)
    _, repo = prepare_ledger(audit)
    a = repo.get("run-neutral")
    with pytest.raises(PersistenceConflict):
        repo.compare_and_swap(a, owned(a), owner="owner", session_id="session")
    def write(_):
        with execution_fence(ExecutionFence("run-neutral", "owner")):
            try:
                repo.compare_and_swap(a, owned(a), owner="owner", session_id="session")
                return True
            except PersistenceConflict:
                return False
    with ThreadPoolExecutor(2) as workers:
        assert sorted(workers.map(write, range(2))) == [False, True]
    with engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM claim_extraction_runs")).scalar_one() == 1
    engine.dispose()


def test_budget_reset_ticket_delete_and_unknown_settlement_rejected(storage):
    _, repo = storage
    a = repo.get("run-neutral")
    ticket = ExtractionTicket(key="a"*64, result_key="b"*64, batch_id="b", tokens=100,
        attempts=1, time_ms=1000, timeout_seconds=1)
    state = owned(a).model_copy(update=dict(tickets={ticket.key: ticket}, calls=1, tokens=100, attempts=1, time_ms=1000))
    a = repo.compare_and_swap(a, state, owner="owner", session_id="session")
    for change in (dict(tokens=0), dict(tickets={}, calls=0, tokens=0, attempts=0, time_ms=0),
                   dict(tickets={ticket.key: ticket.model_copy(update=dict(charged_tokens=0))}, tokens=0),
                   dict(tickets={ticket.key: ticket.model_copy(update=dict(status="failed", charged_attempts=0))}, attempts=0)):
        with pytest.raises(ValueError):
            repo.compare_and_swap(a, a.state.model_copy(update=change), owner="owner", session_id="session")
    assert repo.get("run-neutral").state.tokens == 100
    other = ticket.model_copy(update=dict(key="c"*64, batch_id="next"))
    with pytest.raises(PersistenceConflict, match="unknown"):
        repo.compare_and_swap(a, a.state.model_copy(update=dict(tickets={ticket.key: ticket, other.key: other},
            tokens=200, calls=2, attempts=2, time_ms=2000)), owner="owner", session_id="session")


def test_reservation_lease_bound_cannot_be_omitted_by_caller(storage):
    _, repo = storage
    a = repo.get("run-neutral")
    repo.clock = lambda: datetime.now(timezone.utc) + timedelta(seconds=1199)
    ticket = ExtractionTicket(key="a"*64, result_key="b"*64, batch_id="b", tokens=100,
        attempts=1, time_ms=60000, timeout_seconds=60)
    state = owned(a).model_copy(update=dict(tickets={ticket.key: ticket}, calls=1, tokens=100, attempts=1, time_ms=60000))
    with pytest.raises(PersistenceConflict, match="lease"):
        repo.compare_and_swap(a, state, owner="owner", session_id="session")
    assert repo.get("run-neutral").state.tickets == {}


def test_result_identity_and_invalid_final_commit_do_not_damage_ledger(storage):
    _, repo = storage
    a = repo.get("run-neutral")
    result = ExtractionResult(resource_id="r", resource_version=1, review_id="review", content_hash="a"*64,
        evidence_hash="b"*64, generation_attempt=1, created_at=datetime.now(timezone.utc))
    key = result_identity_key(result, a.policy_hash)
    a = repo.compare_and_swap(a, owned(a).model_copy(update={"results": {key: result}}), owner="owner", session_id="session")
    for changes in (dict(review_id="other"), dict(resource_version=2), dict(status="completed", final_result_hash="0"*64)):
        with pytest.raises(ValueError):
            repo.compare_and_swap(a, a.state.model_copy(update={"results": {key: result.model_copy(update=changes)}}), owner="owner", session_id="session")
        assert repo.get("run-neutral").revision == a.revision


def test_creation_failure_after_run_insert_rolls_back_both(tmp_path, monkeypatch):
    from app.db.audit import sql_repository
    for audit in (MemoryAuditRepository(), sqlite_repository(tmp_path)[0]):
        def fail(*args, **kwargs):
            raise RuntimeError("injected create failure")
        target = audit if isinstance(audit, MemoryAuditRepository) else sql_repository
        name = "_append_event" if isinstance(audit, MemoryAuditRepository) else "add_sql_creation"
        with monkeypatch.context() as patch:
            patch.setattr(target, name, fail)
            with pytest.raises(RuntimeError):
                prepare_ledger(audit)
        assert audit.get_run("run-neutral") is None
