from types import SimpleNamespace

import pytest

from app.db.audit.memory import MemoryAuditRepository
from app.models.shared.persistence import CreateRunCommand, canonical_hash, build_checkpoint_projection
from app.services.generation.lecture_policy import freeze_lecture_policy, resolve_lecture_dispatch
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner


def frozen():
    req = SimpleNamespace(include_review=True, resource_types=["讲义"])
    settings = SimpleNamespace(lecture_review_strategy="lecture_issue_v1", lecture_review_context_tokens=64000, llm_max_output_tokens=16000)
    return freeze_lecture_policy(req, settings)


def test_submission_and_dispatch_freeze():
    fields = frozen()
    dispatch = {"workflow_version": "learning_documents.lecture_issue.v1", "base_workflow_version": "learning_documents.v1", **fields}
    dispatch["lecture_dispatch_hash"] = canonical_hash(dispatch)
    assert resolve_lecture_dispatch(dispatch) == ("learning_documents.v1", fields)
    for key in fields:
        bad = dict(dispatch)
        del bad[key]
        with pytest.raises(ValueError):
            resolve_lecture_dispatch(bad)
    assert freeze_lecture_policy(SimpleNamespace(include_review=False, resource_types=["讲义"]), SimpleNamespace(lecture_review_strategy="lecture_issue_v1")) == {}


def test_runner_uses_creation_hash_and_event_not_runtime_presence():
    repo = MemoryAuditRepository()
    snapshot = {"topic": "test", **frozen()}
    repo.create_run(CreateRunCommand(run_id="run", topic="test", request_snapshot=snapshot, request_hash=canonical_hash(snapshot)))
    runner = DurableWorkflowRunner(None, repo)
    state = {"run_id": "run", **frozen()}
    runner._validate_lecture_entry(state)
    with pytest.raises(ValueError):
        runner._validate_lecture_entry({"run_id": "run"})
    repo.runs["run"]["input_payload"]["topic"] = "modified"
    repo.runs["run"]["request_hash"] = canonical_hash(repo.runs["run"]["input_payload"])
    with pytest.raises(ValueError):
        runner._validate_lecture_entry(state)


def test_checkpoint_preserves_policy_but_never_body_or_ledger():
    state = {"run_id": "run", **frozen(), "lecture_ledgers": {"spec": {"private_body": "secret"}}, "lecture_revision": {"previous_content": "secret"}}
    projection = build_checkpoint_projection(state)
    assert projection["lecture_review_policy"] == state["lecture_review_policy"]
    assert "lecture_ledgers" not in projection
    assert "lecture_revision" not in projection



def test_recovery_rejects_committed_review_without_checkpoint():
    repo = SimpleNamespace(get_run_creation_snapshot=lambda run: frozen(), list_checkpoints=lambda run: [], list_steps=lambda run: [
        SimpleNamespace(node_name="review", status="success", step_id="review-step")])
    runner = DurableWorkflowRunner(None, repo)
    with pytest.raises(ValueError, match="observation_incomplete"):
        runner._restore_lecture_ledgers({"run_id": "run", **frozen()})


def test_recovery_rejects_removed_checkpoint_references():
    cp = SimpleNamespace(step_id="review-step", step_sequence=1, event_sequence=2,
        checkpoint_id="checkpoint", state_projection={**frozen(), "review_audit_refs": [{"step_id": "review-step"}]})
    cp.state_hash = canonical_hash(cp.state_projection)
    repo = SimpleNamespace(get_run_creation_snapshot=lambda run: frozen(), list_checkpoints=lambda run: [cp], list_steps=lambda run: [])
    runner = DurableWorkflowRunner(None, repo)
    with pytest.raises(ValueError, match="references"):
        runner._restore_lecture_ledgers({"run_id": "run", **frozen(), "review_audit_refs": []})


def test_unknown_strategy_is_rejected():
    with pytest.raises(ValueError, match="unknown"):
        freeze_lecture_policy(SimpleNamespace(include_review=True, resource_types=["讲义"]),
                              SimpleNamespace(lecture_review_strategy="typo"))


def test_recovery_rejects_checkpoint_deleted_policy_even_with_new_hash():
    cp = SimpleNamespace(step_id="review-step", state_projection={"run_id": "run"})
    cp.state_hash = canonical_hash(cp.state_projection)
    repo = SimpleNamespace(get_run_creation_snapshot=lambda run: frozen(), list_checkpoints=lambda run: [cp])
    with pytest.raises(ValueError, match="checkpoint frozen"):
        DurableWorkflowRunner(None, repo)._restore_lecture_ledgers({"run_id": "run", **frozen()})


@pytest.mark.parametrize("tamper", ["comparison", "decision", "targets"])
def test_recovery_replays_actual_body_decision_and_frozen_targets(tamper):
    from app.models.reviews.review_audit import review_audit_envelope
    from tests.unit.agents.test_lecture_audit_v2 import record
    from app.models.reviews.lecture_review import LectureTargetCoverageV1
    audit = record()
    ledger = audit.lecture_ledgers[0]
    observation = ledger.observations[0]
    binding = ledger.binding.model_copy(update={"evidence_snapshot_hash": canonical_hash({"evidence": []})})
    output = observation.output.model_copy(update={"binding": binding})
    if tamper == "targets":
        output = output.model_copy(update={"targets": [LectureTargetCoverageV1(target="extra", status="covered")]})
    observation = observation.model_copy(update={"binding": binding, "output": output,
        "output_hash": canonical_hash(output.model_dump(mode="json")),
        **({"comparison_hash": "f" * 64} if tamper == "comparison" else {}),
        **({"decision": "revise"} if tamper == "decision" else {})})
    ledger = ledger.model_copy(update={"binding": binding, "observations": [observation]})
    audit = audit.model_copy(update={"lecture_ledgers": [ledger],
        **({"decision": "revise", "resources": [audit.resources[0].model_copy(update={"decision": "revise"})]} if tamper == "decision" else {})})
    envelope = review_audit_envelope(audit, run_id="run", step_id="step1")
    reference = {"step_id": "step1", "audit_hash": envelope["audit_hash"], "review_ids": ["review"],
        "schema_version": "2.0", "lecture_resources": [{"resource_id": "resource", "resource_spec_id": "spec",
        "version": binding.version, "content_hash": binding.content_hash, "lineage_id": binding.lineage_id}]}
    cp = SimpleNamespace(step_id="step1", step_sequence=1, event_sequence=1, checkpoint_id="cp",
        state_projection={**frozen(), "review_audit_refs": [reference]})
    cp.state_hash = canonical_hash(cp.state_projection)
    repo = SimpleNamespace(get_run_creation_snapshot=lambda run: frozen(), list_checkpoints=lambda run: [cp],
        list_steps=lambda run: [], list_evidence=lambda run: [], get_step_review_audit=lambda run, step: audit)
    resource = SimpleNamespace(run_id="run", resource_id="resource", resource_spec_id="spec",
        resource_family_id=binding.lineage_id, version=binding.version, parent_resource_id=None, content_text="题目")
    spec = SimpleNamespace(run_id="run", evidence_ids=[], knowledge_points=["target"])
    resource_repo = SimpleNamespace(get=lambda ident: resource, get_spec=lambda ident: spec)
    runner = DurableWorkflowRunner(None, repo, SimpleNamespace(resource_repository=resource_repo))
    with pytest.raises(ValueError):
        runner._restore_lecture_ledgers({"run_id": "run", **frozen(), "review_audit_refs": [reference]})
