"""G5: contract 2.0 / V3 end-to-end through production nodes and repositories.

A real ``review_node`` (with the V2 engine, request builder, correction, ledger
and V3 audit), ``prepare_revision_node``, ``generate_node``, the original Claim
gate and ``decide_node`` are driven together under a fenced durable review entry,
so the success path publishes and serves Markdown over HTTP, and the failed
correction path stays unpublished with a complete read-back-able repair record.

The gateway and generator are scripted fixtures; every node, router, repository
and publication decision is production code.  Nothing is hand-assembled into the
audit and no resource is set to ``published`` by the test.
"""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.agents.resource_workflows.learning_documents import generator_agent
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_decide_node,
    claim_extract_node,
    claim_judge_node,
)
from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.agents.resource_workflows.learning_documents.workflow import (
    decide_node,
    prepare_revision_node,
    route_after_review,
)
from app.api.learning_documents import documents
from app.core.execution import ExecutionFence, execution_fence
from app.db.audit.memory import MemoryAuditRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.shared.agent_contracts import (
    GeneratedArtifact,
    ResourceArtifactMetadata,
    bind_recorded_step_context,
    reset_recorded_step_context,
)
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    build_checkpoint_projection,
    canonical_hash,
)
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for

INITIAL_CONTENT = "## 融合公式\n融合公式为 1/(k+r)。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。"
REVISED_CONTENT = "## 融合公式\n融合公式为 1/(k+r)，其中 k 固定为 60，r 为名次。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。"
OWNER = "owner-e2e"


def _loc(payload, paragraph_id):
    return {"paragraph_id": paragraph_id, "heading_path": payload["heading_paths"][paragraph_id], "quote": None}


def _coverage_issue(payload, target, *, issue_id="tmp-1"):
    return {
        "issue_id": issue_id, "code": "coverage_gap", "severity": "high", "blocking": True,
        "blocking_rule": "target_coverage", "dimension": "coverage", "affected_target_ids": [target],
        "location": _loc(payload, "p000002"), "impact": "读者学不到该目标",
        "requirement": "补充公式推导与示例", "acceptance": "正文出现该目标的推导与例句",
        "criteria_version": 1, "path": "reorganize_existing", "evidence_refs": [],
        "teaching_rule_id": "target_coverage", "executability": "executable",
        "rationale": "可整理已有材料",
    }


def _missing_first(call):
    """First answer marks targets[0] missing with no linked issue -> TARGET_LINK_MISSING."""
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": _loc(payload, "p000002")} for item in frozen[1:]]
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def _missing_with_issue(call):
    """Legal correction: the missing goal now carries its blocking coverage issue."""
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": _loc(payload, "p000002")} for item in frozen[1:]]
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0,
            "issues": [_coverage_issue(payload, frozen[0])], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def _recheck_fixed(call):
    """Recheck answer: all goals covered and the open issue is marked fixed."""
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": item, "status": "covered", "reason": "正文已讲解",
             "location": _loc(payload, "p000002")} for item in frozen]
    old_id = payload["old_issues"][0]["issue"]["issue_id"]
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [],
            "resolutions": [{"issue_id": old_id, "result": "fixed", "reason": "已补充名次与 k 的说明",
                             "current_location": _loc(payload, "p000002"), "previous_location": None,
                             "evidence_refs": []}],
            "reopen": [], "omitted_blocking_issues": False}


def _v2_state(targets, *, run_id, include_claim=True):
    state = state_for()
    state.update(run_id=run_id, target_skill_nodes=list(targets))
    specs = build_resource_specs(
        run_id=run_id, resource_types=["讲义"], topic="题目", difficulty="初级",
        learning_plan={}, evidence=state["retrieved_evidence"], target_skill_nodes=list(targets))
    policy = LectureReviewPolicyV2(context_tokens=1_000_000, max_output_tokens=12000,
                                   max_physical_attempts=2).model_dump(mode="json")
    learner = LearnerProfile(learner_id=f"learner-{run_id}", learner_type="测试", education="本科",
                             major="测试", learning_goal="测试")
    state.update(
        learner=learner, learner_id=learner.learner_id, resource_types=["讲义"],
        resource_specs=[s.model_dump(mode="json") for s in specs], topic="题目",
        generated_resources=[], include_review=True, include_claim_check=include_claim,
        max_iterations=2, lecture_review_contract_version="2.0",
        lecture_review_policy=policy, lecture_review_policy_hash=canonical_hash(policy),
        lecture_ledgers={}, generation_mode="standard", revision_count=0, claim_revision_count=0)
    return state, specs[0]


def _durable_repo(run_id, state, *, owner=OWNER):
    repo = MemoryAuditRepository()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    snapshot = {
        "lecture_review_contract_version": state["lecture_review_contract_version"],
        "lecture_review_policy": state["lecture_review_policy"],
        "lecture_review_policy_hash": state["lecture_review_policy_hash"],
    }
    repo.create_run(CreateRunCommand(run_id=run_id, request_snapshot=snapshot,
                                     request_hash=canonical_hash(snapshot),
                                     owner_instance_id=owner, lease_expires_at=expires))
    repo.start_run(run_id, occurred_at=now, lease_expires_at=expires)
    return repo, now


def _review(repo, run_id, state, gateway, sequence):
    """Run the real review node under a recorded step + fenced owner/lease.

    This mirrors ``RecordedNode.__call__`` (begin step -> node -> complete step
    with the review audit) but uses an explicit monotonic step sequence because
    the surrounding generator/revision nodes are driven directly in this test.
    """
    step_id = f"{run_id}:review:{sequence}"
    now = datetime.now(timezone.utc)
    repo.begin_step(BeginStepCommand(
        run_id=run_id, step_id=step_id, step_sequence=sequence, node_name="review",
        agent_name="reviewer", action="review", generation_attempt=state["generation_attempt"],
        started_at=now, lease_expires_at=now + timedelta(hours=1)))
    token = bind_recorded_step_context({"step_id": step_id, "sequence": sequence,
                                        "attempt": state["generation_attempt"], "node_name": "review",
                                        "started_at": now})
    try:
        with execution_fence(ExecutionFence(run_id=run_id, owner=OWNER)):
            output = review_node(state, llm_gateway=gateway, review_repository=repo)
    finally:
        reset_recorded_step_context(token)
    trace = next(item for item in reversed(output.get("trace", [])) if item.get("step_id") == step_id)
    repo.complete_step(CompleteStepCommand(
        run_id=run_id, step_id=step_id, trace=trace, review_audit=output.get("review_audit"),
        ended_at=datetime.now(timezone.utc)))
    return output


def _checkpoint(repo, run_id, state, sequence):
    """Persist the checkpoint a completed review step must leave behind."""
    step_id = state["review_audit_refs"][-1]["step_id"]
    projection = build_checkpoint_projection(state)
    repo.save_checkpoint(run_id=run_id, step_id=step_id, step_sequence=sequence, node_name="review",
                         state_projection=projection, state_hash=canonical_hash(projection),
                         occurred_at=datetime.now(timezone.utc))
    return step_id


def _generator(*, revised_content):
    def generate(spec, context, **kwargs):
        revision = (context.constraints or {}).get("lecture_revision")
        content = revised_content if revision else INITIAL_CONTENT
        return GeneratedArtifact(
            metadata=ResourceArtifactMetadata(
                resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
                resource_type="讲义", representation="text", agent_name="frozen",
                prompt_version="1", artifact_format="markdown", source_evidence_ids=spec.evidence_ids),
            difficulty="初级", mime_type="text/markdown", content_text=content,
            knowledge_points=spec.knowledge_points)
    return SimpleNamespace(agent_name="frozen", prompt_version="1", artifact_format="markdown",
                           generate=generate)


@pytest.mark.parametrize("targets,expected_first_rate", [
    (["融合分计算"], 0.0),
    (["融合分计算", "名次来源说明"], 0.5),
], ids=["single-target", "multi-target"])
def test_v2_revision_recheck_claim_publication_markdown(targets, expected_first_rate, monkeypatch):
    run_id = f"run-e2e-{len(targets)}"
    state, spec = _v2_state(targets, run_id=run_id)
    repo, _ = _durable_repo(run_id, state)
    gateway = ScriptedLLMGateway([_missing_first, _missing_with_issue, _recheck_fixed])
    monkeypatch.setattr(generator_agent, "get_resource_agent",
                        lambda _: _generator(revised_content=REVISED_CONTENT))

    # Initial generation.
    state.update(generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([])))

    # First review: contradiction -> bounded correction -> valid revise (V3).
    state.update(_review(repo, run_id, state, gateway, sequence=1))
    assert state["review_result"]["decision"] == "revise"
    assert route_after_review(state) == "prepare_revision"
    first_step = _checkpoint(repo, run_id, state, sequence=1)

    # V3 read-back: the correction chain and ledger are durable.
    first_v3 = repo.get_step_review_audit(run_id, first_step)
    assert first_v3.schema_version == "3.0"
    assert first_v3.repairs[0].corrected is True
    assert tuple(first_v3.repairs[0].error_codes) == ("TARGET_LINK_MISSING",)
    assert len(first_v3.lecture_ledgers) == 1
    assert len(first_v3.lecture_ledgers[0].observations) == 1
    assert first_v3.lecture_ledgers[0].observations[-1].coverage_rate == expected_first_rate
    old_issue_id = first_v3.lecture_ledgers[0].issues[0].issue.issue_id
    old_resource_id = state["generated_resources"][0].resource_id

    # Targeted revision per frozen spec, then recheck that closes the issue.
    state.update(prepare_revision_node(state))
    assert spec.resource_spec_id in state["lecture_revision"]
    state.update(generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([])))
    revised = state["generated_resources"][0]
    assert revised.parent_resource_id == old_resource_id and revised.version == 2

    state.update(_review(repo, run_id, state, gateway, sequence=2))
    assert state["review_result"]["decision"] == "approve"
    assert route_after_review(state) == "claim_extract"
    second_step = _checkpoint(repo, run_id, state, sequence=2)

    recheck_v3 = repo.get_step_review_audit(run_id, second_step)
    assert recheck_v3.schema_version == "3.0"
    assert len(recheck_v3.lecture_ledgers[0].observations) == 2
    ledger = state["lecture_ledgers"][spec.resource_spec_id]
    assert ledger["issues"][0]["issue"]["issue_id"] == old_issue_id
    assert ledger["issues"][0]["status"] == "closed"

    # Original Claim gate.
    def extract(call):
        payload = json.loads(call["messages"][1].content)
        resource = payload["resources"][0]
        content = state["generated_resources"][0].content_text
        text = next((line.strip() for line in content.splitlines()
                     if len(line.strip()) > 10 and not line.lstrip().startswith("#")), content)[:80]
        start = content.index(text)
        return {"resources": [{"resource_id": resource["resource_id"], "claims": [{
            "claim_text": text, "claim_type": "factual", "source_text": text,
            "source_start": start, "source_end": start + len(text),
            "knowledge_point_id": spec.knowledge_points[0],
            "source_evidence_ids": [payload["allowed_evidence"][0]["evidence_id"]]}]}]}

    def judge(call):
        payload = json.loads(call["messages"][1].content)
        return {"judgements": [{"claim_id": claim["claim_id"], "verdict": "supported",
                                "evidence_ids": [payload["allowed_evidence"][0]["evidence_id"]],
                                "reason": "冻结证据支持", "confidence": .99} for claim in payload["claims"]]}

    state.update(claim_extract_node(state, llm_gateway=ScriptedLLMGateway([extract])))
    state.update(claim_judge_node(state, llm_gateway=ScriptedLLMGateway([judge])))
    state.update(claim_decide_node(state))
    state.update(decide_node(state))

    resource = state["generated_resources"][0]
    assert resource.publication_status == "published"
    assert resource.claim_metric_status == "complete"

    # HTTP Markdown read of the published artifact.
    repo_resources = MemoryResourceRepository()
    repo_resources.save(resource, state["learner_id"], "题目")
    profiles = MemoryLearnerRepository()
    profiles.save(state["learner"])
    app = FastAPI()
    app.container = SimpleNamespace(resource_service=lambda: ResourceService(repo_resources),
                                    profile_service=lambda: ProfileService(profiles))
    app.include_router(documents.router, prefix="/api/resources")
    response = TestClient(app).get("/api/resources/items/" + resource.resource_id)
    assert response.status_code == 200
    assert response.json()["resource"]["content_text"] == resource.content_text == REVISED_CONTENT
    assert response.json()["resource"]["mime_type"] == "text/markdown"


def test_v2_correction_failure_stays_unpublished(monkeypatch):
    """A correction that fails again must not publish and must keep a full repair."""
    run_id = "run-e2e-fail"
    state, spec = _v2_state(["融合分计算", "名次来源说明"], run_id=run_id)
    repo, _ = _durable_repo(run_id, state)
    # Both first and correction answers stay inconsistent -> correction_failed.
    gateway = ScriptedLLMGateway([_missing_first, _missing_first])
    monkeypatch.setattr(generator_agent, "get_resource_agent",
                        lambda _: _generator(revised_content=REVISED_CONTENT))

    state.update(generator_agent.generate_node(state, llm_gateway=ScriptedLLMGateway([])))
    state.update(_review(repo, run_id, state, gateway, sequence=1))

    assert state["review_result"]["decision"] == "human_review"
    assert state["lecture_stop_reasons"][spec.resource_spec_id].startswith("correction_failed:")
    assert spec.resource_spec_id not in state["lecture_ledgers"]

    first_step = _checkpoint(repo, run_id, state, sequence=1)
    v3 = repo.get_step_review_audit(run_id, first_step)
    assert v3.schema_version == "3.0"
    repair = v3.repairs[0]
    assert repair.attempted and not repair.corrected
    assert repair.first_output is not None
    assert repair.correction_call_id is not None and repair.correction_call_id != repair.first_call_id
    assert "TARGET_LINK_MISSING" in repair.error_codes
    assert v3.lecture_ledgers == []

    # The failed round must not route to revision and must never publish.
    assert route_after_review(state) != "prepare_revision"
    state.update(decide_node(state))
    assert state["generated_resources"][0].publication_status == "unpublished"
