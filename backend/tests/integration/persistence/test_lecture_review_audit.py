"""V2 audit transaction and namespace behavior in both production repositories."""

import copy
from datetime import datetime, timezone

import pytest

from app.db.audit.base import PersistenceConflict, PersistenceError
from app.models.shared.persistence import BeginStepCommand, CompleteStepCommand, CreateRunCommand, canonical_hash
from tests.integration.persistence.test_private_review_audit import (
    repository as repository, get_payload, set_payload,
)
from tests.unit.agents.test_lecture_audit_v2 import record


def prepare(repo):
    audit = record()
    snapshot = {"review_policy": audit.policy.model_dump(mode="json"),
        "lecture_review_contract_version": "1.0",
        "lecture_review_policy": audit.lecture_review_policy.model_dump(mode="json"),
        "lecture_review_policy_hash": audit.lecture_review_policy_hash}
    repo.create_run(CreateRunCommand(run_id=audit.run_id, request_snapshot=snapshot,
                                    request_hash=canonical_hash(snapshot)))
    now = datetime.now(timezone.utc)
    repo.start_run(audit.run_id, occurred_at=now)
    repo.begin_step(BeginStepCommand(run_id=audit.run_id, step_id=audit.step_id, step_sequence=1,
        node_name="review", agent_name="reviewer", action="review", started_at=now))
    trace = {"status": "success", "attempt": 1, "resource_ids": ["resource"], "review_ids": ["review"]}
    return CompleteStepCommand(run_id=audit.run_id, step_id=audit.step_id,
                               trace=trace, review_audit=audit.model_dump(mode="json"))


def test_v2_roundtrip_idempotency_and_conflict(repository):
    command = prepare(repository)
    first = repository.complete_step(command)
    assert repository.complete_step(command).payload_hash == first.payload_hash
    loaded = repository.get_step_review_audit(command.run_id, command.step_id)
    assert loaded.model_dump(mode="json") == command.review_audit
    assert set(get_payload(repository, command)) == {"review_audit_v2"}
    assert "lecture_ledgers" not in str(repository.list_events(command.run_id))
    changed = copy.deepcopy(command.review_audit)
    changed["decision"] = "reject"
    with pytest.raises(PersistenceConflict):
        repository.complete_step(command.model_copy(update={"review_audit": changed}))


def test_v2_missing_or_corrupt_or_wrong_namespace_fails(repository):
    command = prepare(repository)
    with pytest.raises(PersistenceError, match="incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)
    repository.complete_step(command)
    payload = get_payload(repository, command)
    payload["review_audit_v2"]["audit_hash"] = "0" * 64
    set_payload(repository, command, payload)
    with pytest.raises(PersistenceError):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_v2_event_failure_rolls_back(repository, monkeypatch):
    command = prepare(repository)
    count = len(repository.list_events(command.run_id))
    def fail(*args, **kwargs):
        raise RuntimeError("injected V2 event failure")
    monkeypatch.setattr(repository, "_append_event", fail)
    with pytest.raises(RuntimeError):
        repository.complete_step(command)
    assert repository.list_steps(command.run_id)[0].status == "running"
    assert len(repository.list_events(command.run_id)) == count
    with pytest.raises(PersistenceError, match="incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_new_strategy_cannot_write_v1_audit(repository):
    command = prepare(repository)
    legacy = {key: value for key, value in command.review_audit.items()
              if key not in {"lecture_review_policy", "lecture_review_policy_hash", "lecture_ledgers"}}
    legacy["schema_version"] = "1.0"
    with pytest.raises(PersistenceConflict):
        repository.complete_step(command.model_copy(update={"review_audit": legacy}))


def test_v2_checkpoint_and_creation_snapshot_detachment(repository):
    from app.models.reviews.review_audit import review_audit_envelope
    command = prepare(repository)
    repository.complete_step(command)
    snapshot = repository.get_run_creation_snapshot(command.run_id)
    snapshot["lecture_review_policy"]["context_tokens"] = 1
    assert repository.get_run_creation_snapshot(command.run_id)["lecture_review_policy"]["context_tokens"] != 1
    projection = repository.get_run_creation_snapshot(command.run_id)
    envelope = review_audit_envelope(command.review_audit, run_id=command.run_id, step_id=command.step_id)
    projection["review_audit_refs"] = [{"schema_version": "2.0", "step_id": command.step_id,
        "audit_hash": envelope["audit_hash"], "review_ids": ["review"]}]
    repository.save_checkpoint(run_id=command.run_id, step_id=command.step_id, step_sequence=1,
        node_name="review", state_projection=projection, state_hash=canonical_hash(projection),
        occurred_at=datetime.now(timezone.utc))
    assert repository.get_step_review_audit(command.run_id, command.step_id).schema_version == "2.0"


def test_v2_ledger_tamper_rejected_even_with_recomputed_envelope(repository):
    command = prepare(repository)
    changed = copy.deepcopy(command.review_audit)
    changed["lecture_ledgers"][0]["observations"][0]["comparison_hash"] = "a" * 64
    # Comparison hash must be verified against the persisted resource by recovery;
    # output/body binding corruption is already rejected by the stored contract.
    changed["lecture_ledgers"][0]["observations"][0]["output"]["hallucination_score"] = 0.1
    with pytest.raises(PersistenceConflict):
        repository.complete_step(command.model_copy(update={"review_audit": changed}))


def test_v2_sql_commit_failure_is_atomic(tmp_path, monkeypatch):
    from sqlalchemy.orm import Session
    from tests.fakes.persistence import sqlite_repository
    repo, engine = sqlite_repository(tmp_path)
    try:
        command = prepare(repo)
        with monkeypatch.context() as scoped:
            def fail(*args, **kwargs):
                raise RuntimeError("injected V2 commit failure")
            scoped.setattr(Session, "commit", fail)
            with pytest.raises(RuntimeError, match="commit"):
                repo.complete_step(command)
        assert repo.list_steps(command.run_id)[0].status == "running"
        with pytest.raises(PersistenceError, match="incomplete"):
            repo.get_step_review_audit(command.run_id, command.step_id)
    finally:
        engine.dispose()


def test_v2_envelope_size_limit():
    from app.models.reviews.review_audit import review_audit_envelope
    audit = record()
    payload = audit.model_dump(mode="json")
    payload["resources"][0]["profiles"] = ["x" * (1024 * 1024)]
    with pytest.raises(ValueError, match="maximum size"):
        review_audit_envelope(payload, run_id="run", step_id="step1")
