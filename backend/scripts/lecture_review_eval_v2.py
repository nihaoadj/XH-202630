"""V2 offline engine replay: frozen scenarios through the production V2 engine.

This is the engine-level companion to the validator-only ``test_lecture_review_v2_eval``.
Each frozen case is turned into a real ``review_lecture_v2`` call (request build,
correction, ledger, derived decision) against a scripted gateway, with a legal
durable review entry, so the frozen dataset is exercised through production code
rather than by constructing an already-valid output and calling the validator.

``real_model_quality`` stays ``NOT_RUN_LIVE``: the gateway is scripted.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.lecture_engine_v2 import review_lecture_v2
from app.agents.resource_workflows.learning_documents.reviewing.telemetry import ReviewCallCollector
from app.core.execution import ExecutionFence, execution_fence
from app.db.audit.memory import MemoryAuditRepository
from app.models.knowledge.knowledge import EvidenceItem
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.lecture_review_v2 import LectureReviewPolicyV2
from app.models.shared.llm import LLMCallContext
from app.models.shared.persistence import BeginStepCommand, CreateRunCommand, canonical_hash

from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import state_for

TOPICS = {
    "topic_a": "## 融合公式\n融合公式为 1/(k+r)，k 固定，r 为名次。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。",
    "topic_b": "## 命令\n`grep -n` 在输出中附带行号。\n\n## 练习\n对日志文件执行 grep -n 并记录输出。",
    "topic_c": "## 能量守恒\n能量守恒说明能量不会凭空产生或消失。\n\n## 练习\n列出两种能量转换并说明守恒。",
}
RULES = {"self_contained", "target_coverage", "difficulty", "organization", "synthetic_input"}
CORRECTABLE = {"TARGET_LINK_MISSING", "RISK_SCORE_CONFLICT"}


def _loc(content, paragraph):
    return {"paragraph_id": paragraph, "heading_path": paragraph_heading_paths(content)[paragraph], "quote": None}


def _issue(content, *, dimension, targets=(), rule="self_contained", executable="executable"):
    return {"issue_id": f"tmp-{dimension}-{rule}", "code": "coverage_gap" if dimension == "coverage" else "structure_quality",
            "severity": "high", "blocking": True, "blocking_rule": rule, "dimension": dimension,
            "affected_target_ids": list(targets), "location": _loc(content, "p000002"),
            "impact": "读者无法达到该目标", "requirement": "补充必要内容与材料",
            "acceptance": "读者可仅凭本讲义完成要求", "criteria_version": 1,
            "path": "evidence_insufficient" if executable != "executable" else "reorganize_existing",
            "evidence_refs": [], "teaching_rule_id": rule, "executability": executable,
            "rationale": "按冻结证据整理已有材料"}


def _output(content, binding, *, targets, scenario):
    dims = {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"}
    rows = [{"target": item, "status": "covered", "reason": "正文已讲解", "location": _loc(content, "p000002")}
            for item in targets]
    issues, score = [], 0.0
    if scenario in {"covered_missing_input", "missing_and_missing_input"}:
        dims["self_contained"] = "fail"
        issues.append(_issue(content, dimension="self_contained", rule="self_contained"))
    if scenario in {"missing_complete_exercise", "missing_and_missing_input", "evidence_insufficient",
                    "missing_without_issue"}:
        rows[0] = {"target": targets[0], "status": "missing", "reason": "正文只有名词"}
    if scenario in {"missing_complete_exercise", "missing_and_missing_input", "evidence_insufficient"}:
        issues.append(_issue(content, dimension="coverage", targets=[targets[0]], rule="target_coverage"))
    if scenario == "evidence_insufficient":
        issues[-1].update({"path": "evidence_insufficient", "executability": "evidence_insufficient"})
    if scenario == "factual_error":
        dims["factual_evidence"] = "fail"
        issues.append(_issue(content, dimension="factual_evidence", rule="difficulty"))
        score = 0.8
    if scenario == "risk_conflict":
        score = 0.7  # factual pass but high risk -> RISK_SCORE_CONFLICT
    return {"binding": binding, "dimensions": dims, "targets": rows, "hallucination_score": score,
            "issues": issues, "resolutions": [], "reopen": [], "omitted_blocking_issues": False}


def _corrected_output(content, binding, *, targets, scenario):
    """A legal second answer for the whitelisted contradiction scenarios."""
    out = _output(content, binding, targets=targets, scenario=scenario)
    if scenario == "risk_conflict":
        out["hallucination_score"] = 0.0
    elif scenario == "missing_without_issue":
        out["issues"].append(_issue(content, dimension="coverage", targets=[targets[0]], rule="target_coverage"))
    return out


def evaluate_v2(manifest_path):
    data = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if data.get("contract_version") != "2.0" or len(data.get("cases", [])) < 1:
        raise ValueError("lecture v2 frozen manifest incomplete")
    results = []
    for case in data["cases"]:
        content = TOPICS[case["topic"]]
        targets = case["targets"]
        results.append(_evaluate_case_v2(case, content, targets))
    return {"schema_version": "1.0", "contract_version": "2.0",
            "status": "PASS" if all(r["passed"] for r in results) else "FAIL",
            "evidence_type": "offline_engine_replay", "real_model_quality": "NOT_RUN_LIVE",
            "end_to_end": "NOT_RUN",
            "manifest_hash": hashlib.sha256(Path(manifest_path).read_bytes()).hexdigest(),
            "results": results}


def _evaluate_case_v2(case, content, targets):
    state = state_for()
    run_id = f"eval-v2-{case['case_id']}"
    spec_id = "spec-eval-v2"
    resource = state["generated_resources"][0].model_copy(update={
        "resource_type": "讲义", "resource_spec_id": spec_id, "resource_family_id": "lineage-eval-v2",
        "resource_id": f"res-{case['case_id']}", "version": 1, "content_text": content,
        "knowledge_points": list(targets), "practice_guide_payload": None, "practice_guide_payload_hash": None})
    policy = LectureReviewPolicyV2(context_tokens=1_000_000, max_output_tokens=12000,
                                   max_physical_attempts=2).model_dump(mode="json")
    state.update(run_id=run_id, generated_resources=[resource], lecture_review_policy=policy,
                 lecture_review_policy_hash=canonical_hash(policy), lecture_ledgers={},
                 lecture_review_contract_version="2.0", max_iterations=2, revision_count=0,
                 retrieved_evidence=[])
    state["resource_specs"] = [{"resource_spec_id": spec_id, "resource_family_id": "lineage-eval-v2",
                                "knowledge_points": list(targets), "difficulty": resource.difficulty}]

    # A scripted first answer, plus a legal correction when the scenario is a
    # whitelisted contradiction (matched on the frozen error code, not the
    # scenario label, because CORRECTABLE holds error codes).
    scenario = case["scenario"]
    expected_error = case.get("expected_error_code")

    def scripted(call):
        payload = json.loads(call["messages"][1].content)
        binding = payload["binding"]
        # The correction request carries the first output under review.
        if "previous_review_under_check" in payload and expected_error in CORRECTABLE:
            return _corrected_output(content, binding, targets=targets, scenario=scenario)
        return _output(content, binding, targets=targets, scenario=scenario)

    gateway = ScriptedLLMGateway([scripted, scripted])
    collector = ReviewCallCollector()
    step = f"step-{case['case_id']}"
    owner = "eval-owner"

    repo = MemoryAuditRepository()
    now = datetime.now(timezone.utc)
    expires = now + timedelta(hours=1)
    repo.create_run(CreateRunCommand(run_id=run_id, request_snapshot={}, request_hash=canonical_hash({}),
                                     owner_instance_id=owner, lease_expires_at=expires))
    repo.start_run(run_id, occurred_at=now, lease_expires_at=expires)
    repo.begin_step(BeginStepCommand(run_id=run_id, step_id=step, step_sequence=1, node_name="reviewer",
                                     agent_name="reviewer", action="review", started_at=now,
                                     lease_expires_at=expires))

    from app.agents.resource_workflows.learning_documents.reviewing.lecture_guard import assert_review_entry_allowed

    def guard(*, step_id, generation_attempt):
        assert_review_entry_allowed(repository=repo, run_id=run_id, step_id=step_id,
                                    generation_attempt=generation_attempt)

    error = None
    actual = None
    repair_codes = []
    logical_calls = 0
    with execution_fence(ExecutionFence(run_id=run_id, owner=owner)):
        try:
            outcome = review_lecture_v2(
                state=state, resource=resource, evidence=[], step_id=step,
                context=LLMCallContext(run_id=run_id, step_id=step, node_name="reviewer",
                                       schema_name="LectureInitialReviewV2"),
                gateway=gateway, collector=collector, review_id=f"{step}-rid", step_guard=guard)
            actual = outcome.raw["decision"]
            if outcome.repair is not None:
                repair_codes = list(outcome.repair.error_codes)
            logical_calls = len(gateway.calls)
        except Exception as exc:  # noqa: BLE001 — engine replays must not crash the whole report
            error = str(exc)

    if expected_error:
        # A contradiction scenario: the first answer must be flagged, and (for
        # whitelisted codes) corrected into a legal outcome.
        passed = bool(repair_codes) and (expected_error in repair_codes or "correction" in (error or ""))
    else:
        passed = actual == case["expected_decision"] and error is None
    return {"case_id": case["case_id"], "scenario": scenario, "passed": passed,
            "expected_decision": case.get("expected_decision"), "expected_error_code": expected_error,
            "actual_decision": actual, "repair_error_codes": repair_codes,
            "logical_calls": logical_calls, "error": error}
