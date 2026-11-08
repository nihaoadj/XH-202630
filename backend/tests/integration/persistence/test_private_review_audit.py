import copy
from datetime import datetime, timezone

import pytest
from sqlalchemy.orm import Session

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.db.audit.base import PersistenceConflict, PersistenceError
from app.db.audit.memory import MemoryAuditRepository
from app.db.shared.models import AgentStepORM
from app.models.reviews.review_audit import AUDIT_NAMESPACE, ReviewAuditRecordV1, review_audit_envelope
from app.models.shared.persistence import BeginStepCommand, CompleteStepCommand, CreateRunCommand, build_checkpoint_projection, canonical_hash
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.persistence import sqlite_repository
from tests.fakes.resource_reviews import approve, case, combined_output, scope_output, state_for


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        yield MemoryAuditRepository()
    else:
        repo, engine = sqlite_repository(tmp_path)
        yield repo
        engine.dispose()


def prepare(repo, *, modern=True, status="success"):
    state = state_for()
    output = review_node(state, llm_gateway=ScriptedLLMGateway([approve()]))
    trace = dict(output["trace"][0], status=status)
    snapshot = {"review_policy": state["review_policy"]} if modern else {}
    repo.create_run(CreateRunCommand(run_id=state["run_id"], request_snapshot=snapshot, request_hash=canonical_hash(snapshot)))
    now = datetime.now(timezone.utc)
    repo.start_run(state["run_id"], occurred_at=now)
    repo.begin_step(BeginStepCommand(run_id=state["run_id"], step_id=trace["step_id"], step_sequence=1,
                                    node_name="review", agent_name="reviewer", action="审核", started_at=now))
    command = CompleteStepCommand(run_id=state["run_id"], step_id=trace["step_id"], trace=trace,
                                   review_audit=output["review_audit"])
    return state, output, command


def set_payload(repo, command, payload):
    if isinstance(repo, MemoryAuditRepository):
        repo.step_output_payloads[command.run_id][command.step_id] = copy.deepcopy(payload)
    else:
        with repo.session_factory() as db:
            db.query(AgentStepORM).filter_by(step_id=command.step_id).one().output_payload = copy.deepcopy(payload)
            db.commit()


def get_payload(repo, command):
    if isinstance(repo, MemoryAuditRepository):
        return copy.deepcopy(repo.step_output_payloads[command.run_id][command.step_id])
    with repo.session_factory() as db:
        return copy.deepcopy(db.query(AgentStepORM).filter_by(step_id=command.step_id).one().output_payload)


def test_private_audit_roundtrip_new_session_namespace_and_deepcopy(repository):
    _, output, command = prepare(repository)
    set_payload(repository, command, {"other_namespace": {"kept": True}})
    step = repository.complete_step(command)
    expected = copy.deepcopy(command.review_audit)
    command.review_audit["decision"] = "reject"
    loaded = repository.get_step_review_audit(command.run_id, command.step_id)
    assert loaded.model_dump(mode="json") == expected
    loaded.resources[0].profiles.append("external-mutation")
    assert "external-mutation" not in repository.get_step_review_audit(command.run_id, command.step_id).resources[0].profiles
    assert get_payload(repository, command)["other_namespace"] == {"kept": True}
    assert "review_audit" not in step.model_dump()
    assert "review_audit_v1" not in str(repository.list_steps(command.run_id))
    assert "prompt_fingerprint" not in str(repository.list_events(command.run_id))
    assert output["review_audit"]["calls"][0]["call_id"] == loaded.calls[0].call_id


def test_terminal_same_audit_idempotent_but_edit_delete_and_append_conflict(repository):
    _, _, command = prepare(repository)
    first = repository.complete_step(command)
    assert repository.complete_step(command).payload_hash == first.payload_hash
    for changed in [None, dict(command.review_audit, decision="reject")]:
        with pytest.raises(PersistenceConflict):
            repository.complete_step(command.model_copy(update={"review_audit": changed}))


def test_legacy_hash_stays_identical_and_cannot_append_audit(repository):
    _, _, command = prepare(repository, modern=False)
    legacy = command.model_copy(update={"review_audit": None})
    step = repository.complete_step(legacy)
    assert repository.get_step_review_audit(command.run_id, command.step_id) is None
    # Exact old hash materials, selected from the same public trace.
    keys = {"status", "attempt", "input_summary", "output_summary", "decision_reason", "evidence_refs", "resource_ids", "review_ids",
            "retry_count", "error_code", "llm_call_id", "model_name", "provider_request_id", "structured_output_mode", "finish_reason",
            "input_tokens", "output_tokens", "total_tokens", "llm_duration_ms", "llm_attempts", "workflow_elapsed_ms", "workflow_remaining_ms"}
    assert step.payload_hash == canonical_hash({k: v for k, v in command.trace.items() if k in keys and v is not None})
    with pytest.raises(PersistenceConflict):
        repository.complete_step(command)


def test_new_missing_success_audit_and_interrupted_observation_are_distinct(repository):
    _, _, command = prepare(repository)
    with pytest.raises(PersistenceError, match="observation incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)
    repository.complete_step(command.model_copy(update={"review_audit": None}))
    with pytest.raises(PersistenceError, match="completed review audit missing"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_failed_new_step_is_incomplete_not_legacy(repository):
    _, _, command = prepare(repository, status="failed")
    repository.complete_step(command.model_copy(update={"review_audit": None}))
    with pytest.raises(PersistenceError, match="observation incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_audit_survives_fault_before_checkpoint_then_validates_reference(repository):
    state, output, command = prepare(repository)
    repository.complete_step(command)
    # Simulate artifact recorder failure after complete_step, before checkpoint.
    assert repository.list_checkpoints(command.run_id) == []
    assert repository.get_step_review_audit(command.run_id, command.step_id) is not None
    projection = build_checkpoint_projection({**state, **output})
    assert "review_audit" not in projection
    assert "findings" not in str(projection["review_audit_refs"])
    repository.save_checkpoint(run_id=command.run_id, step_id=command.step_id, step_sequence=1, node_name="review",
        state_projection=projection, state_hash=canonical_hash(projection), occurred_at=datetime.now(timezone.utc))
    assert repository.get_step_review_audit(command.run_id, command.step_id) is not None


@pytest.mark.parametrize("wrong", ["missing", "hash", "reviews"])
def test_existing_checkpoint_with_wrong_reference_is_corruption(repository, wrong):
    state, output, command = prepare(repository)
    repository.complete_step(command)
    projection = build_checkpoint_projection({**state, **output})
    if wrong == "missing":
        projection.pop("review_audit_refs")
    elif wrong == "hash":
        projection["review_audit_refs"][0]["audit_hash"] = "0" * 64
    else:
        projection["review_audit_refs"][0]["review_ids"] = []
    repository.save_checkpoint(run_id=command.run_id, step_id=command.step_id, step_sequence=1, node_name="review",
        state_projection=projection, state_hash=canonical_hash(projection), occurred_at=datetime.now(timezone.utc))
    with pytest.raises(PersistenceError, match="checkpoint audit reference"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_hash_tampering_and_foreign_run_or_policy_rejected(repository):
    _, _, command = prepare(repository)
    for audit in [dict(command.review_audit, run_id="other"), dict(command.review_audit,
            policy={**command.review_audit["policy"], "assessment_strategy": "combined_v2", "combined_context_tokens": 262144})]:
        with pytest.raises(PersistenceConflict):
            repository.complete_step(command.model_copy(update={"review_audit": audit}))
    repository.complete_step(command)
    payload = get_payload(repository, command)
    payload[AUDIT_NAMESPACE]["audit_hash"] = "0" * 64
    set_payload(repository, command, payload)
    with pytest.raises(PersistenceError, match="hash mismatch"):
        repository.get_step_review_audit(command.run_id, command.step_id)
    repository.create_run(CreateRunCommand(run_id="foreign-run", request_snapshot={}, request_hash=canonical_hash({})))
    with pytest.raises((PersistenceConflict, PersistenceError)):
        repository.complete_step(command.model_copy(update={"run_id": "foreign-run"}))


def test_event_failure_rolls_back_step_and_audit_atomically(repository, monkeypatch):
    _, _, command = prepare(repository)
    count = len(repository.list_events(command.run_id))
    def fail(*args, **kwargs):
        raise RuntimeError("injected event failure")
    monkeypatch.setattr(repository, "_append_event", fail)
    with pytest.raises(RuntimeError, match="injected"):
        repository.complete_step(command)
    assert repository.list_steps(command.run_id)[0].status == "running"
    assert len(repository.list_events(command.run_id)) == count
    with pytest.raises(PersistenceError, match="observation incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_sql_commit_failure_does_not_leave_audit(tmp_path, monkeypatch):
    repo, engine = sqlite_repository(tmp_path)
    _, _, command = prepare(repo)
    with monkeypatch.context() as scoped:
        def fail_commit(*args, **kwargs):
            raise RuntimeError("injected commit failure")
        scoped.setattr(Session, "commit", fail_commit)
        with pytest.raises(RuntimeError, match="commit failure"):
            repo.complete_step(command)
    assert repo.list_steps(command.run_id)[0].status == "running"
    with pytest.raises(PersistenceError, match="observation incomplete"):
        repo.get_step_review_audit(command.run_id, command.step_id)
    engine.dispose()


def test_schema_bound_prevents_oversized_ledger():
    output = review_node(state_for(), llm_gateway=ScriptedLLMGateway([approve()]))
    audit = ReviewAuditRecordV1.model_validate(output["review_audit"])
    audit.calls[0].fragment_versions["oversize"] = "x" * (1024 * 1024)
    with pytest.raises(ValueError, match="maximum size"):
        review_audit_envelope(audit, run_id=audit.run_id, step_id=audit.step_id)


def test_evidence_validation_failure_rolls_back_private_audit(repository):
    from app.models.shared.persistence import PersistedEvidenceSnapshot
    from tests.fakes.evidence import make_evidence
    _, _, command = prepare(repository)
    snapshot = PersistedEvidenceSnapshot.from_evidence(make_evidence(), run_id="other-run", retrieval_step_id=command.step_id)
    with pytest.raises(PersistenceConflict):
        repository.complete_step(command.model_copy(update={"evidence": [snapshot]}))
    assert repository.list_steps(command.run_id)[0].status == "running"
    with pytest.raises(PersistenceError, match="observation incomplete"):
        repository.get_step_review_audit(command.run_id, command.step_id)


def test_private_findings_do_not_enter_review_summary_or_timeline(repository):
    _, _, command = prepare(repository)
    repository.complete_step(command)
    review = {"review_id": "private-projection", "passed": True, "status": "approved",
              "specialized_reviews": {"private": "SENTINEL_PRIVATE_FINDINGS"},
              "review_audit": {"private": "SENTINEL_PRIVATE_FINDINGS"}}
    repository.save_review("resource-projection", review, command.run_id)
    assert "SENTINEL_PRIVATE_FINDINGS" not in str(repository.list_reviews_by_run(command.run_id))
    assert "SENTINEL_PRIVATE_FINDINGS" not in repository.get_review_by_resource("resource-projection").model_dump_json()


@pytest.mark.parametrize("strategy", ["two_stage_v1", "combined_v2"])
def test_model_summary_answer_echo_is_safe_before_sql_or_memory_public_projection(repository, strategy):
    sample = case("assessment.clean.01")
    answer = sample["resource"]["assessment_payload"]["node_blocks"][0]["short_answer_questions"][0]["reference_answer"]
    summary = approve()
    summary.update(decision="revise", suggestion=answer,
        issues=[{"code": "structure_quality", "severity": "high", "description": "q-001：" + answer}],
        revision_instructions=[{"issue_codes": ["structure_quality"], "target_resource_type": "分阶测试题", "action": "q-001：" + answer}])
    combined = combined_output(sample)
    combined["summary"] = summary
    outcomes = [combined] if strategy == "combined_v2" else [scope_output(sample), summary]
    result = review_node(state_for(sample, strategy=strategy), llm_gateway=ScriptedLLMGateway(outcomes))
    resource_id = sample["resource"]["resource_id"]
    item = result["resource_review_results"][resource_id]
    repository.save_review(resource_id, item, None)
    for public in [result["review_result"], item, repository.list_reviews_by_run(None), repository.get_review_by_resource(resource_id).model_dump()]:
        assert answer not in str(public)
    assert item["decision"] == "revise"
    assert "q-001" in item["revision_instructions"][0]["action"]
    assert result["review_audit"]["calls"][-1]["status"] == "success"
