"""G3/G4 boundary tests: attempt-detail accounting and correction-failure diagnostics.

G3 — a result whose attempt detail is empty, disagrees with attempt_count, has
an invalid ordinal, or a mismatched call identity must stop the round without a
fresh correction, never treating "0 details" as "0 attempts already spent".

G4 — when the correction request fails at the gateway, the round still yields a
complete read-back-able repair record (first error + first output/hash + the two
call identities + stop reason + actual attempts) and stays unpublished.
"""

import json

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine_v2 import review_lecture_v2
from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.core.llm.gateway import LLMGatewayError
from app.models.shared.common import ErrorInfo
from app.models.reviews.lecture_review_v2 import LectureReviewOutputV2, LectureReviewPolicyV2
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


def lecture_state(*, attempts=2):
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


def location(content, paragraph):
    return {"paragraph_id": paragraph, "heading_path": paragraph_heading_paths(content)[paragraph], "quote": None}


def missing_first(call):
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": location(CONTENT, "p000002")} for item in frozen[1:]]
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def result_with(output, *, n=1, call_id="call-1", attempts=None, attempt_count=None):
    usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
    detail = attempts if attempts is not None else [
        LLMAttemptSummary(attempt=index, status="success", latency_ms=2,
                          structured_output_mode=StructuredOutputMode.TEXT, usage=usage)
        for index in range(1, n + 1)]
    return LLMCallResult(
        output=LectureReviewOutputV2.model_validate(output), call_id=call_id, model_name="fake",
        structured_output_mode=StructuredOutputMode.TEXT,
        attempt_count=attempt_count if attempt_count is not None else n,
        retry_count=n - 1, latency_ms=2, finish_reason="stop", usage=usage, attempts=detail)


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


def first_missing_payload():
    state, resource = lecture_state(attempts=2)
    return state, resource, missing_first


def test_empty_attempt_detail_is_not_zero():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([lambda call: result_with(missing_first(call), n=1,
                                                           attempts=[], attempt_count=1)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1  # no correction was sent
    assert outcome.ledger is None
    assert outcome.raw["decision"] == "human_review"
    assert outcome.stop_reason == "attempt_unknown:ATTEMPT_DETAIL_MISSING"
    assert outcome.repair is not None and not outcome.repair.attempted


def test_attempt_count_disagreement_is_not_zero():
    state, resource = lecture_state(attempts=3)
    gateway = ScriptedLLMGateway([lambda call: result_with(missing_first(call), n=1,
                                                           attempts=[
                                                               LLMAttemptSummary(attempt=1, status="success", latency_ms=2,
                                                                                 structured_output_mode=StructuredOutputMode.TEXT,
                                                                                 usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2))],
                                                           attempt_count=2)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.stop_reason == "attempt_unknown:ATTEMPT_COUNT_MISMATCH"


def test_invalid_ordinal_is_not_zero():
    state, resource = lecture_state(attempts=3)
    usage = LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2)
    gateway = ScriptedLLMGateway([lambda call: result_with(missing_first(call), n=2, attempts=[
        LLMAttemptSummary(attempt=2, status="success", latency_ms=2,
                          structured_output_mode=StructuredOutputMode.TEXT, usage=usage),
        LLMAttemptSummary(attempt=3, status="success", latency_ms=2,
                          structured_output_mode=StructuredOutputMode.TEXT, usage=usage)])])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.stop_reason == "attempt_unknown:ATTEMPT_ORDINAL_INVALID"


def test_attempt_cap_exceeded_is_blocked():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([lambda call: result_with(missing_first(call), n=3)])
    outcome, _ = invoke(state, resource, gateway)
    assert len(gateway.calls) == 1
    assert outcome.stop_reason == "attempt_unknown:ATTEMPT_CAP_EXCEEDED"


def _gateway_error(call_id="correction-call"):
    return LLMGatewayError(
        error=ErrorInfo(code="LLM_UPSTREAM_UNAVAILABLE", category="transient", message="upstream timeout",
                        retryable=True, source="reviewer", attempt=1),
        call_id=call_id, retry_count=1, latency_ms=5,
        attempts=[LLMAttemptSummary(attempt=1, status="failed", latency_ms=5,
                                    error_code="timeout",
                                    structured_output_mode=StructuredOutputMode.TEXT,
                                    usage=LLMUsage(input_tokens=1, output_tokens=0, total_tokens=1))])


def test_correction_gateway_failure_yields_complete_repair():
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([missing_first, _gateway_error()])
    outcome, collector = invoke(state, resource, gateway)
    assert len(gateway.calls) == 2  # first + one failed correction, no third request
    assert outcome.ledger is None
    assert outcome.raw["decision"] == "human_review"
    assert outcome.stop_reason.startswith("correction_gateway_error:")
    repair = outcome.repair
    assert repair is not None
    assert repair.attempted and not repair.corrected
    assert repair.first_output is not None
    assert repair.first_output_hash == canonical_hash(repair.first_output)
    assert repair.correction_call_id == "correction-call"
    assert repair.first_call_id != repair.correction_call_id
    assert "TARGET_LINK_MISSING" in repair.error_codes


def test_repair_final_call_id_derivation():
    from app.models.reviews.review_audit import ReviewRepairRecordV3
    state, resource = lecture_state(attempts=2)
    gateway = ScriptedLLMGateway([missing_first, _gateway_error()])
    outcome, _ = invoke(state, resource, gateway)
    record = ReviewRepairRecordV3.model_validate(outcome.repair.as_dict() | {"review_id": "rid"})
    # Uncorrected -> final call is still the first call.
    assert record.final_call_id == record.first_call_id


def _missing_with_issue(call, *, issue_id="tmp-1"):
    payload = json.loads(call["messages"][1].content)
    frozen = list(payload["targets"])
    rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
    rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
              "location": location(CONTENT, "p000002")} for item in frozen[1:]]
    issue = {"issue_id": issue_id, "code": "coverage_gap", "severity": "high", "blocking": True,
             "blocking_rule": "target_coverage", "dimension": "coverage", "affected_target_ids": [frozen[0]],
             "location": location(CONTENT, "p000002"), "impact": "学不到该目标",
             "requirement": "补充推导", "acceptance": "正文出现推导", "criteria_version": 1,
             "path": "reorganize_existing", "evidence_refs": [], "teaching_rule_id": "target_coverage",
             "executability": "executable", "rationale": "可整理已有材料"}
    return {"binding": payload["binding"],
            "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
            "targets": rows, "hallucination_score": 0.0, "issues": [issue], "resolutions": [], "reopen": [],
            "omitted_blocking_issues": False}


def test_duplicate_temporary_ids_are_blocked_before_server_replacement():
    # Two issues that both use the same temporary id must be rejected before the
    # server assigns stable ids, so they cannot silently become two new issues.
    state, resource = lecture_state(attempts=2)

    def two_duplicate_issues(call):
        payload = json.loads(call["messages"][1].content)
        frozen = list(payload["targets"])
        rows = [{"target": frozen[0], "status": "missing", "reason": "正文只有名词"}]
        rows += [{"target": item, "status": "covered", "reason": "正文已讲解",
                  "location": location(CONTENT, "p000002")} for item in frozen[1:]]
        base = _missing_with_issue(call)
        second = json.loads(json.dumps(base["issues"][0]))
        second["affected_target_ids"] = [frozen[0]]
        return {**base, "issues": [base["issues"][0], second]}

    gateway = ScriptedLLMGateway([two_duplicate_issues, _missing_with_issue])
    outcome, _ = invoke(state, resource, gateway)
    # The duplicate-temp-id error is whitelisted and corrected once into a valid revise.
    assert len(gateway.calls) == 2
    assert outcome.repair.corrected and "ISSUE_ID_DUPLICATED" in outcome.repair.error_codes
    assert outcome.ledger is not None

