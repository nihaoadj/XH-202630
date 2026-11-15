"""V2 engine: one derived decision, one bounded correction, exact physical accounting."""

import hashlib
import json

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine_v2 import review_lecture_v2
from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.shared.llm import (
    LLMAttemptSummary,
    LLMCallContext,
    LLMCallResult,
    LLMUsage,
    StructuredOutputMode,
)
from app.models.shared.persistence import canonical_hash
from tests.fakes.lecture_guard import fenced, legal_review_entry, step_guard_factory
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for

TARGETS = ["融合分计算", "名次来源说明"]
CONTENT = "## 融合公式\n融合公式为 1/(k+r)。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。"


def lecture_state(*, attempts=2, content=CONTENT):
    state = state_for()
    resource = state["generated_resources"][0].model_copy(update={
        "resource_type": "讲义", "resource_spec_id": "spec-1", "resource_family_id": "lineage-1",
        "resource_id": "res-1", "version": 1, "content_text": content,
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


def location(content, paragraph):
    return {"paragraph_id": paragraph, "heading_path": paragraph_heading_paths(content)[paragraph], "quote": None}


def output_for(binding, targets, *, content=CONTENT, dims=None, issues=None, score=0.0, resolutions=None):
    return {
        "binding": binding,
        "dimensions": dims or {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": targets,
        "hallucination_score": score,
        "issues": issues or [],
        "resolutions": resolutions or [],
        "reopen": [],
        "omitted_blocking_issues": False,
    }


def covered(target, content=CONTENT):
    return {"target": target, "status": "covered", "reason": "正文已讲解", "location": location(content, "p000002")}


def coverage_issue(content=CONTENT, target=TARGETS[0], blocking=True):
    return {
        "issue_id": "tmp-coverage", "code": "coverage_gap", "severity": "high" if blocking else "low",
        "blocking": blocking, "blocking_rule": "target_coverage" if blocking else None,
        "dimension": "coverage", "affected_target_ids": [target],
        "location": location(content, "p000002"),
        "impact": "读者学不到该目标", "requirement": "补充公式推导",
        "acceptance": "正文出现该目标的推导与例句", "criteria_version": 1,
        "path": "reorganize_existing", "evidence_refs": [],
        "teaching_rule_id": "target_coverage", "executability": "executable", "rationale": "可整理已有材料",
    }


def attempts(n, *, call_id="call-1"):
    usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    return LLMCallResult(
        output={"placeholder": True}, call_id=call_id, model_name="fake-model",
        structured_output_mode=StructuredOutputMode.TEXT, attempt_count=n, retry_count=n - 1,
        latency_ms=2, finish_reason="stop", usage=usage,
        attempts=[LLMAttemptSummary(attempt=index, status="success", latency_ms=2,
                                    structured_output_mode=StructuredOutputMode.TEXT, usage=usage)
                  for index in range(1, n + 1)])


def result_with(output: dict, *, n=1, call_id="call-1"):
    """Wrap a V2 payload in a real LLMCallResult carrying ``n`` physical attempts."""
    from app.models.reviews.lecture_review_v2 import LectureReviewOutputV2
    base = attempts(n, call_id=call_id)
    return base.model_copy(update={"output": LectureReviewOutputV2.model_validate(output)})


def builder(*, targets=None, missing=False, issue=False, dims=None, score=0.0, binding_patch=None):
    """Return a scripted builder that reads the frozen payload from the request."""
    def build(call):
        payload = json.loads(call["messages"][1].content)
        frozen = list(payload["targets"])
        if missing:
            rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
            rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
                      "location": location(CONTENT, "p000002")} for item in frozen[1:]]
        else:
            rows = [covered(item) for item in frozen]
        binding = dict(payload["binding"])
        binding.update(binding_patch or {})
        return output_for(binding, rows, dims=dims, score=score,
                          issues=[coverage_issue()] if issue else [])
    return build


def invoke(state, resource, gateway, *, step="review-step"):
    collector = ReviewCallCollector()
    repo, run_id, step_id, owner = legal_review_entry(run_id=state["run_id"], step_id=step)
    guard = step_guard_factory(repo, run_id=run_id, owner=owner)
    with fenced(run_id, owner):
        outcome = review_lecture_v2(
            state=state, resource=resource, evidence=state["retrieved_evidence"], step_id=step_id,
            context=LLMCallContext(run_id=state["run_id"], step_id=step_id, node_name="reviewer",
                                   schema_name="LectureInitialReviewV2"),
            gateway=gateway, collector=collector, review_id="rid", step_guard=guard)
    return outcome, collector


def test_contradiction_is_corrected_into_a_valid_revise():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([builder(missing=True), builder(missing=True, issue=True)])
    outcome, collector = invoke(state, resource, gateway)

    assert len(gateway.calls) == 2
    assert outcome.repair.corrected and outcome.repair.error_codes == ("TARGET_LINK_MISSING",)
    assert outcome.ledger is not None and len(outcome.ledger.observations) == 1
    assert outcome.ledger.observations[-1].decision == "revise"
    assert outcome.ledger.observations[-1].coverage_rate == 0.5
    assert outcome.raw["decision"] == "revise"
    assert {call.status for call in collector.calls} == {"invalid_result", "success"}
    second = gateway.calls[1]["options"]
    assert second.max_attempts == 1 and second.allow_schema_repair is False and second.schema_repair_attempts == 0


def test_correction_never_asks_for_approval():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([builder(missing=True), builder(missing=True, issue=True)])
    invoke(state, resource, gateway)
    system_text = gateway.calls[1]["messages"][0].content
    body = json.loads(gateway.calls[1]["messages"][1].content)
    assert "不要为了满足结构虚构缺陷" in system_text
    assert "approve" not in system_text
    assert body["review_consistency_errors"] == [
        {"code": "TARGET_LINK_MISSING", "field": "targets[融合分计算]",
         "relationship": "a missing goal requires a concrete blocking coverage issue with a requirement and acceptance"}]
    assert body["previous_review_under_check"]["targets"]


def test_single_physical_attempt_cannot_correct():
    state, resource = lecture_state(attempts=1)
    gateway = ScriptedLLMGateway([builder(missing=True)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.ledger is None
    assert outcome.raw["decision"] == "human_review"
    assert outcome.stop_reason == "no_physical_attempt_left"
    assert not outcome.repair.corrected


def test_first_call_consuming_the_budget_blocks_correction():
    state, resource = lecture_state(attempts=2)
    scripted = builder(missing=True)
    gateway = ScriptedLLMGateway([lambda call: result_with(scripted(call), n=2)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.ledger is None and outcome.stop_reason == "no_physical_attempt_left"


def test_three_attempt_budget_still_allows_only_one_correction():
    state, resource = lecture_state(attempts=3)
    gateway = ScriptedLLMGateway([builder(missing=True), builder(missing=True, issue=True)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 2
    assert outcome.repair.corrected and outcome.repair.first_attempts == 1
    assert outcome.repair.correction_attempts == 1
    assert outcome.repair.first_call_id != outcome.repair.correction_call_id


def test_failed_correction_stays_unpublished():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([builder(missing=True), builder(missing=True)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 2
    assert outcome.ledger is None
    assert outcome.raw["decision"] == "human_review"
    assert outcome.stop_reason.startswith("correction_failed:")
    assert outcome.repair.attempted and not outcome.repair.corrected


def test_non_whitelisted_error_is_not_corrected():
    state, resource = lecture_state(attempts=3)
    gateway = ScriptedLLMGateway([builder(binding_patch={"run_id": "another-run"})])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.ledger is None
    assert outcome.stop_reason == "not_correctable:BINDING_MISMATCH"


def test_deadline_blocks_the_correction():
    class DeadlineGateway(ScriptedLLMGateway):
        def remaining_seconds(self, context):
            return 0.0

    state, resource = lecture_state(attempts=3)
    gateway = DeadlineGateway([builder(missing=True)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.stop_reason == "workflow_deadline_reached"


def test_same_content_cannot_be_fixed():
    state, resource = lecture_state(attempts=3)
    first = ScriptedLLMGateway([builder(missing=True, issue=True)])
    outcome, _ = invoke(state, resource, first)
    old_id = outcome.ledger.issues[0].issue.issue_id
    state["lecture_ledgers"] = {resource.resource_spec_id: outcome.ledger.model_dump(mode="json")}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": CONTENT}}
    revised = resource.model_copy(update={"version": 2, "resource_id": "res-2",
                                          "parent_resource_id": resource.resource_id})

    def fix(call):
        payload = json.loads(call["messages"][1].content)
        rows = [covered(item) for item in payload["targets"]]
        return output_for(payload["binding"], rows, resolutions=[{
            "issue_id": old_id, "result": "fixed", "reason": "已修改",
            "current_location": location(CONTENT, "p000002"),
            "previous_location": location(CONTENT, "p000002"), "evidence_refs": []}])

    gateway = ScriptedLLMGateway([fix])
    second, _ = invoke(state, revised, gateway, step="review-2")
    assert len(gateway.calls) == 1
    assert second.ledger is None
    assert second.stop_reason == "not_correctable:UNCHANGED_FIXED"


def test_false_positive_does_not_approve_a_new_factual_defect():
    state, resource = lecture_state(attempts=3)
    first = ScriptedLLMGateway([builder(missing=True, issue=True)])
    outcome, _ = invoke(state, resource, first)
    old_id = outcome.ledger.issues[0].issue.issue_id
    state["lecture_ledgers"] = {resource.resource_spec_id: outcome.ledger.model_dump(mode="json")}
    state["lecture_revision"] = {resource.resource_spec_id: {"previous_content": CONTENT}}
    revised = resource.model_copy(update={"version": 2, "resource_id": "res-2",
                                          "parent_resource_id": resource.resource_id})

    factual = {
        "issue_id": "tmp-fact", "code": "factual_risk", "severity": "critical", "blocking": True,
        "blocking_rule": "evidence", "dimension": "factual_evidence", "affected_target_ids": [],
        "location": location(CONTENT, "p000002"), "impact": "结论与证据相反",
        "requirement": "改为与证据一致的表述", "acceptance": "正文不再出现该错误断言",
        "criteria_version": 1, "path": "reorganize_existing", "evidence_refs": [],
        "teaching_rule_id": "difficulty", "executability": "executable", "rationale": "需按证据改写"}

    def recheck(call):
        payload = json.loads(call["messages"][1].content)
        rows = [covered(item) for item in payload["targets"]]
        rows[0] = {"target": payload["targets"][0], "status": "covered", "reason": "正文已讲解",
                   "location": location(CONTENT, "p000002")}
        return output_for(payload["binding"], rows,
                          dims={"factual_evidence": "fail", "difficulty": "pass", "self_contained": "pass"},
                          score=0.8, issues=[factual],
                          resolutions=[{"issue_id": old_id, "result": "false_positive", "reason": "父版已满足",
                                        "previous_location": location(CONTENT, "p000002"), "evidence_refs": []}])

    gateway = ScriptedLLMGateway([recheck])
    second, _ = invoke(state, revised, gateway, step="review-2")
    assert second.ledger is not None
    assert second.ledger.observations[-1].decision == "revise"
    assert second.raw["decision"] == "revise"
    open_codes = {item.issue.code for item in second.ledger.issues if item.status == "open"}
    assert open_codes == {"factual_risk"}
