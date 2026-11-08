"""Durable V2 guard and V3 audit: both repositories, no resumed review without a chain."""

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine_v2 import review_lecture_v2
from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import (
    LectureStepGuardError,
    assert_no_unfinished_review,
    assert_review_entry_allowed,
)
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.reviews.review_audit import (
    ReviewAuditRecordV3,
    ReviewResourceAuditV1,
    review_audit_envelope,
    select_audit_envelope,
    summarize_review_calls,
)
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    canonical_hash,
)
from tests.fakes.lecture_guard import fenced, legal_review_entry, step_guard_factory
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for
from tests.integration.persistence.test_private_review_audit import repository as repository  # noqa: F401

TARGETS = ["融合分计算", "名次来源说明"]
CONTENT = "## 融合公式\n融合公式为 1/(k+r)。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。"
OWNER = "owner-1"


def start(repo, run_id="run-guard", *, owner=OWNER, lease_seconds=3600):
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=lease_seconds)
    repo.create_run(CreateRunCommand(run_id=run_id, request_snapshot={}, request_hash=canonical_hash({}),
                                     owner_instance_id=owner, lease_expires_at=expires))
    repo.start_run(run_id, occurred_at=now, lease_expires_at=expires)
    return now


def begin(repo, step_id, *, node="reviewer", sequence=1, now=None, run_id="run-guard"):
    repo.begin_step(BeginStepCommand(run_id=run_id, step_id=step_id, step_sequence=sequence,
                                    node_name=node, agent_name="reviewer", action="review",
                                    started_at=now or datetime.now(timezone.utc)))


def allowed(repo, *, run_id="run-guard", step_id, generation_attempt=1, owner=OWNER):
    with fenced(run_id, owner):
        assert_review_entry_allowed(repository=repo, run_id=run_id, step_id=step_id,
                                    generation_attempt=generation_attempt)


def test_guard_requires_a_recorded_step(repository):  # noqa: F811
    start(repository)
    with pytest.raises(LectureStepGuardError, match="not_recorded"):
        allowed(repository, step_id="missing")


def test_guard_requires_a_repository():
    with pytest.raises(LectureStepGuardError, match="repository_missing"):
        assert_review_entry_allowed(repository=None, run_id="run-guard", step_id="x", generation_attempt=1)


def test_guard_allows_the_only_live_review(repository):  # noqa: F811
    now = start(repository)
    begin(repository, "step-1", now=now)
    allowed(repository, step_id="step-1")


def test_guard_blocks_a_missing_fence(repository):  # noqa: F811
    now = start(repository)
    begin(repository, "step-1", now=now)
    with pytest.raises(LectureStepGuardError, match="fence_missing"):
        assert_review_entry_allowed(repository=repository, run_id="run-guard",
                                    step_id="step-1", generation_attempt=1)


def test_guard_blocks_a_wrong_owner(repository):  # noqa: F811
    now = start(repository, owner=OWNER)
    begin(repository, "step-1", now=now)
    with pytest.raises(LectureStepGuardError, match="owner_mismatch"):
        with fenced("run-guard", "intruder"):
            assert_review_entry_allowed(repository=repository, run_id="run-guard",
                                        step_id="step-1", generation_attempt=1)


def test_guard_blocks_an_expired_lease(repository):  # noqa: F811
    now = start(repository, lease_seconds=-60)
    begin(repository, "step-1", now=now)
    with pytest.raises(LectureStepGuardError, match="lease_expired"):
        allowed(repository, step_id="step-1")


def test_guard_blocks_after_an_unfinished_review(repository):  # noqa: F811
    now = start(repository)
    begin(repository, "step-1", now=now, sequence=1)
    begin(repository, "step-2", now=now, sequence=2)
    with pytest.raises(LectureStepGuardError, match="unfinished"):
        allowed(repository, step_id="step-2")


def test_guard_blocks_a_finished_review_without_audit(repository):  # noqa: F811
    now = start(repository)
    begin(repository, "step-1", now=now, sequence=1)
    repository.complete_step(CompleteStepCommand(
        run_id="run-guard", step_id="step-1",
        trace={"status": "success", "attempt": 1, "resource_ids": [], "review_ids": []}))
    begin(repository, "step-2", now=now, sequence=2)
    with pytest.raises(LectureStepGuardError, match="audit_missing"):
        allowed(repository, step_id="step-2")
    with pytest.raises(LectureStepGuardError, match="chain_incomplete"):
        assert_no_unfinished_review(repository=repository, run_id="run-guard")


def lecture_state(attempts=2):
    state = state_for()
    resource = state["generated_resources"][0].model_copy(update={
        "resource_type": "讲义", "resource_spec_id": "spec-1", "resource_family_id": "lineage-1",
        "resource_id": "res-1", "version": 1, "content_text": CONTENT,
        "knowledge_points": list(TARGETS), "practice_guide_payload": None,
        "practice_guide_payload_hash": None})
    policy = LectureReviewPolicyV2(context_tokens=1_000_000, max_output_tokens=12000,
                                   max_physical_attempts=attempts).model_dump(mode="json")
    state.update(generated_resources=[resource], lecture_review_policy=policy,
                 lecture_review_policy_hash=canonical_hash(policy), lecture_ledgers={},
                 lecture_review_contract_version="2.0", max_iterations=2)
    state["resource_specs"] = [{"resource_spec_id": "spec-1", "resource_family_id": "lineage-1",
                                "knowledge_points": list(TARGETS), "difficulty": resource.difficulty}]
    return state, resource


def scripted_repair(call):
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": {"paragraph_id": "p000002",
                           "heading_path": paragraph_heading_paths(CONTENT)["p000002"], "quote": None}}
             for item in frozen[1:]]
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def scripted_valid(call):
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": {"paragraph_id": "p000002",
                           "heading_path": paragraph_heading_paths(CONTENT)["p000002"], "quote": None}}
             for item in frozen[1:]]
    issue = {"issue_id": "tmp-1", "code": "coverage_gap", "severity": "high", "blocking": True,
             "blocking_rule": "target_coverage", "dimension": "coverage",
             "affected_target_ids": [frozen[0]],
             "location": {"paragraph_id": "p000002",
                          "heading_path": paragraph_heading_paths(CONTENT)["p000002"], "quote": None},
             "impact": "学不到该目标", "requirement": "补充推导", "acceptance": "正文出现推导",
             "criteria_version": 1, "path": "reorganize_existing", "evidence_refs": [],
             "teaching_rule_id": "target_coverage", "executability": "executable",
             "rationale": "可整理已有材料"}
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [issue], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def v3_record():
    state, resource = lecture_state()
    gateway = ScriptedLLMGateway([scripted_repair, scripted_valid])
    collector = ReviewCallCollector()
    repo, run_id, step_id, owner = legal_review_entry(run_id=state["run_id"], step_id="step-1")
    guard = step_guard_factory(repo, run_id=run_id, owner=owner)
    with fenced(run_id, owner):
        outcome = review_lecture_v2(
            state=state, resource=resource, evidence=state["retrieved_evidence"], step_id="step-1",
            context=LLMCallContext(run_id=state["run_id"], step_id="step-1", node_name="reviewer",
                                   schema_name="LectureInitialReviewV2"),
            gateway=gateway, collector=collector, review_id="rid", step_guard=guard)
    assert outcome.ledger is not None
    resource_audit = ReviewResourceAuditV1(
        resource_id=resource.resource_id, review_id="rid", resource_spec_id="spec-1",
        resource_type="讲义", structure_status="passed", semantic_status="passed",
        decision="revise", profiles=["lecture_initial_v2"], prompt_fingerprints=["0" * 64])
    return ReviewAuditRecordV3(
        run_id=state["run_id"], step_id="step-1", generation_attempt=1, revision_count=0,
        policy={"schema_version": "1.0"}, decision="revise", node_wall_ms=10,
        resources=[resource_audit], calls=collector.calls,
        summary=summarize_review_calls(collector.calls),
        lecture_review_policy=state["lecture_review_policy"],
        lecture_review_policy_hash=state["lecture_review_policy_hash"],
        lecture_ledgers=[outcome.ledger],
        repairs=[outcome.repair.as_dict() | {"review_id": "rid"}],
    )


def test_v3_envelope_keeps_repair_attachment_and_version():
    record = v3_record()
    envelope = review_audit_envelope(record, run_id=record.run_id, step_id=record.step_id)
    assert envelope["schema_version"] == "3.0"
    assert select_audit_envelope({"review_audit_v3": envelope}) is envelope
    payload = envelope["payload"]
    assert payload["repairs"][0]["corrected"] is True
    assert payload["repairs"][0]["first_output_hash"]
    assert payload["lecture_ledgers"][0]["schema_version"] == "2.0"
    assert payload["lecture_ledgers"][0]["observations"][0]["decision"] == "revise"


def test_v3_repair_attachment_hash_is_enforced():
    record = v3_record()
    tampered = record.repairs[0].model_dump(mode="json")
    tampered["first_output"] = {"tampered": True}
    with pytest.raises(ValueError, match="hash mismatch"):
        ReviewAuditRecordV3.model_validate({**record.model_dump(mode="json"), "repairs": [tampered]})


def test_v3_audit_persists_in_both_repositories(repository):  # noqa: F811
    record = v3_record()
    snapshot = {"review_policy": record.policy.model_dump(mode="json"),
                "lecture_review_contract_version": "2.0",
                "lecture_review_policy": record.lecture_review_policy.model_dump(mode="json"),
                "lecture_review_policy_hash": record.lecture_review_policy_hash}
    now = datetime.now(timezone.utc)
    repository.create_run(CreateRunCommand(run_id=record.run_id, request_snapshot=snapshot,
                                           request_hash=canonical_hash(snapshot)))
    repository.start_run(record.run_id, occurred_at=now)
    repository.begin_step(BeginStepCommand(run_id=record.run_id, step_id=record.step_id,
                                           step_sequence=1, node_name="review", agent_name="reviewer",
                                           action="review", started_at=now))
    command = CompleteStepCommand(
        run_id=record.run_id, step_id=record.step_id,
        trace={"status": "success", "attempt": 1, "resource_ids": ["res-1"], "review_ids": ["rid"]},
        review_audit=record.model_dump(mode="json"))
    repository.complete_step(command)
    loaded = repository.get_step_review_audit(record.run_id, record.step_id)
    assert loaded.schema_version == "3.0"
    assert loaded.repairs[0].corrected is True
    assert "lecture_ledgers" not in str(repository.list_events(record.run_id))
