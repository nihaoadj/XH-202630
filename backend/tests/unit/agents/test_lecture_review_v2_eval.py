"""Frozen V2 focused dataset: 24 cases over three topics, executed by the production validator."""

import hashlib
import json
from pathlib import Path

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract_v2 import (
    validate_lecture_review_v2,
)
from app.agents.resource_workflows.learning_documents.reviewing.lecture_errors import (
    LectureReviewValidationError,
)
from app.models.reviews.lecture_review import LectureReviewBindingV1
from app.models.reviews.lecture_review_v2 import LectureReviewOutputV2

MANIFEST = Path(__file__).resolve().parents[2] / "fixtures/resource_reviews/lecture_issue_v2/manifest.json"
TOPICS = {
    "topic_a": "## 融合公式\n融合公式为 1/(k+r)，k 固定，r 为名次。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。",
    "topic_b": "## 命令\n`grep -n` 在输出中附带行号。\n\n## 练习\n对日志文件执行 grep -n 并记录输出。",
    "topic_c": "## 能量守恒\n能量守恒说明能量不会凭空产生或消失。\n\n## 练习\n列出两种能量转换并说明守恒。",
}
RULES = {"self_contained", "target_coverage", "difficulty", "organization", "synthetic_input"}
MANIFEST_DATA = json.loads(MANIFEST.read_text(encoding="utf-8"))


def binding(content):
    return LectureReviewBindingV1(
        run_id="run-eval", resource_spec_id="spec-eval", lineage_id="lineage-eval", resource_id="res-eval",
        version=1, content_hash=hashlib.sha256(content.encode()).hexdigest(),
        evidence_snapshot_hash=hashlib.sha256(b"snap").hexdigest(),
        policy_hash=hashlib.sha256(b"policy").hexdigest())


def loc(content, paragraph):
    return {"paragraph_id": paragraph, "heading_path": paragraph_heading_paths(content)[paragraph], "quote": None}


def issue(content, *, dimension, targets=(), rule="self_contained", executable="executable"):
    return {
        "issue_id": f"tmp-{dimension}-{rule}", "code": "coverage_gap" if dimension == "coverage" else "structure_quality",
        "severity": "high", "blocking": True, "blocking_rule": rule, "dimension": dimension,
        "affected_target_ids": list(targets), "location": loc(content, "p000002"),
        "impact": "读者无法达到该目标", "requirement": "补充必要内容与材料",
        "acceptance": "读者可仅凭本讲义完成要求", "criteria_version": 1,
        "path": "evidence_insufficient" if executable != "executable" else "reorganize_existing",
        "evidence_refs": [], "teaching_rule_id": rule, "executability": executable,
        "rationale": "按冻结证据整理已有材料"}


def build(case, content, targets):
    dims = {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"}
    rows = [{"target": item, "status": "covered", "reason": "正文已讲解", "location": loc(content, "p000002")}
            for item in targets]
    issues, score = [], 0.0
    scenario = case["scenario"]
    if scenario in {"covered_missing_input", "missing_and_missing_input"}:
        dims["self_contained"] = "fail"
        issues.append(issue(content, dimension="self_contained", rule="self_contained"))
    if scenario in {"missing_complete_exercise", "missing_and_missing_input", "evidence_insufficient",
                    "missing_without_issue"}:
        rows[0] = {"target": targets[0], "status": "missing", "reason": "正文只有名词"}
    if scenario in {"missing_complete_exercise", "missing_and_missing_input", "evidence_insufficient"}:
        issues.append(issue(content, dimension="coverage", targets=[targets[0]], rule="target_coverage"))
    if scenario == "evidence_insufficient":
        issues[-1].update({"path": "evidence_insufficient", "executability": "evidence_insufficient"})
    if scenario == "factual_error":
        dims["factual_evidence"] = "fail"
        issues.append(issue(content, dimension="factual_evidence", rule="difficulty"))
        score = 0.8
    if scenario == "risk_conflict":
        score = 0.7
    return LectureReviewOutputV2.model_validate({
        "binding": binding(content).model_dump(mode="json"), "dimensions": dims, "targets": rows,
        "hallucination_score": score, "issues": issues, "resolutions": [], "reopen": [],
        "omitted_blocking_issues": False})


def test_manifest_is_frozen_and_anonymous():
    assert MANIFEST_DATA["case_count"] == len(MANIFEST_DATA["cases"]) == 24
    assert MANIFEST_DATA["contract_version"] == "2.0"
    for key, text in TOPICS.items():
        assert MANIFEST_DATA["topics"][key]["content_hash"] == hashlib.sha256(text.encode()).hexdigest()
    forbidden = MANIFEST_DATA["anonymity"]["forbidden_tokens"]
    for case in MANIFEST_DATA["cases"]:
        # Only the identifiers the model would see must be opaque; expectations may
        # legitimately contain label words because they never enter a request.
        identifier = " ".join([case["case_id"], case["topic"], *case["targets"]]).lower()
        assert not [token for token in forbidden if token in identifier]


@pytest.mark.parametrize("case", MANIFEST_DATA["cases"], ids=[item["case_id"] for item in MANIFEST_DATA["cases"]])
def test_every_frozen_case_matches_its_expected_outcome(case):
    content = TOPICS[case["topic"]]
    output = build(case, content, case["targets"])
    binding_value = binding(content)
    output = output.model_copy(update={"binding": binding_value})
    if case["expected_error_code"]:
        with pytest.raises(LectureReviewValidationError) as caught:
            validate_lecture_review_v2(
                output=output, binding=binding_value, content=content, previous_content=None,
                targets=case["targets"], evidence_hashes={}, teaching_rule_ids=RULES)
        assert caught.value.code == case["expected_error_code"]
        return
    decision = validate_lecture_review_v2(
        output=output, binding=binding_value, content=content, previous_content=None,
        targets=case["targets"], evidence_hashes={}, teaching_rule_ids=RULES)
    assert decision.decision == case["expected_decision"]
