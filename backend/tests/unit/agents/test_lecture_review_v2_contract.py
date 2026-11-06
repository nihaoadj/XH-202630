"""V2 lecture contract: one coverage source, three independent judgements, typed errors."""

import hashlib
import json

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract_v2 import (
    issue_id_v2,
    validate_lecture_review_v2,
)
from app.agents.resource_workflows.learning_documents.reviewing.lecture_errors import (
    LectureReviewValidationError,
)
from app.models.reviews.lecture_review import LectureReviewBindingV1
from app.models.reviews.lecture_review_v2 import (
    LectureDimensionsV2,
    LectureIssueV2,
    LectureReviewOutputV2,
    derived_coverage_rate,
)

TARGETS = ["融合分计算", "名次来源说明"]
EVIDENCE = {"ev-1": hashlib.sha256("融合公式为加权求和".encode()).hexdigest()}

TOPICS = {
    "数学": {
        "content": "## 融合公式\n融合公式为 1/(k+r)，k 固定，r 为名次。\n\n## 练习\n已知关键词名次为 2，向量名次为 5，k=60，求融合分。",
        "covered_paragraph": "p000002",
        "missing_paragraph": "p000005",
    },
    "软件操作": {
        "content": "## 命令\n`grep -n` 在输出中附带行号。\n\n## 练习\n对日志文件执行 grep -n 并记录输出。",
        "covered_paragraph": "p000002",
        "missing_paragraph": "p000005",
    },
    "自然科学": {
        "content": "## 能量守恒\n能量守恒说明能量不会凭空产生或消失。\n\n## 练习\n列出两种能量转换并说明守恒。",
        "covered_paragraph": "p000002",
        "missing_paragraph": "p000005",
    },
}


def binding_for(content: str) -> LectureReviewBindingV1:
    return LectureReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="lineage-1", resource_id="res-1",
        version=1, content_hash=hashlib.sha256(content.encode()).hexdigest(),
        evidence_snapshot_hash=hashlib.sha256(b"snapshot").hexdigest(),
        policy_hash=hashlib.sha256(b"policy").hexdigest())


def loc(content, paragraph, quote=None):
    return {"paragraph_id": paragraph, "heading_path": paragraph_heading_paths(content)[paragraph], "quote": quote}


def issue(content, *, dimension="coverage", blocking=True, paragraph="p000002", targets=None, rule="target_coverage"):
    return {
        "issue_id": f"tmp-{dimension}-{paragraph}-{blocking}", "code": "coverage_gap" if dimension == "coverage" else "structure_quality",
        "severity": "high" if blocking else "low", "blocking": blocking,
        "blocking_rule": rule if blocking else None,
        "dimension": dimension, "affected_target_ids": targets or [],
        "location": loc(content, paragraph),
        "impact": "读者无法完成要求", "requirement": "补充缺失内容",
        "acceptance": "读者可仅凭本讲义完成", "criteria_version": 1,
        "path": "reorganize_existing", "evidence_refs": [],
        "teaching_rule_id": rule, "executability": "executable", "rationale": "已有材料可整理",
    }


def build(content, *, targets=None, dims=None, issues=None, score=0.0, omitted=False):
    return LectureReviewOutputV2.model_validate({
        "binding": binding_for(content).model_dump(mode="json"),
        "dimensions": dims or {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": targets or [{"target": item, "status": "covered", "reason": "正文已讲解",
                                "location": loc(content, "p000002")} for item in TARGETS],
        "hallucination_score": score, "issues": issues or [], "resolutions": [], "reopen": [],
        "omitted_blocking_issues": omitted,
    })


def validate(content, output, **kwargs):
    binding = binding_for(content)
    output = output.model_copy(update={"binding": binding})
    return validate_lecture_review_v2(
        output=output, binding=binding, content=content, previous_content=None,
        targets=TARGETS, evidence_hashes=EVIDENCE,
        teaching_rule_ids={"self_contained", "target_coverage", "difficulty", "organization", "synthetic_input"},
        **kwargs)


def test_dimensions_have_no_model_coverage_verdict():
    schema = json.dumps(LectureReviewOutputV2.model_json_schema(), ensure_ascii=False)
    assert "coverage_rate" not in schema
    assert '"decision"' not in schema
    dimensions = LectureDimensionsV2.model_fields
    assert set(dimensions) == {"factual_evidence", "difficulty", "self_contained"}


@pytest.mark.parametrize("topic", sorted(TOPICS))
def test_covered_goal_with_missing_practice_input_is_a_material_problem(topic):
    case = TOPICS[topic]
    output = build(case["content"], dims={"factual_evidence": "pass", "difficulty": "pass", "self_contained": "fail"},
                   issues=[issue(case["content"], dimension="self_contained",
                                 paragraph=case["missing_paragraph"], rule="self_contained")])
    decision = validate(case["content"], output)
    assert decision.decision == "revise"
    assert decision.coverage_rate == 1.0
    assert [item.dimension for item in decision.open_issues] == ["self_contained"]


@pytest.mark.parametrize("topic", sorted(TOPICS))
def test_missing_goal_with_complete_practice_is_a_coverage_problem(topic):
    case = TOPICS[topic]
    targets = [
        {"target": TARGETS[0], "status": "missing", "reason": "正文只有名词"},
        {"target": TARGETS[1], "status": "covered", "reason": "正文已讲解",
         "location": loc(case["content"], "p000002")},
    ]
    output = build(case["content"], targets=targets,
                   issues=[issue(case["content"], targets=[TARGETS[0]],
                                 paragraph=case["covered_paragraph"])])
    decision = validate(case["content"], output)
    assert decision.decision == "revise"
    assert decision.coverage_rate == 0.5
    assert decision.open_issues[0].affected_target_ids == [TARGETS[0]]


@pytest.mark.parametrize("topic", sorted(TOPICS))
def test_complete_lecture_approves_without_any_summary_field(topic):
    decision = validate(TOPICS[topic]["content"], build(TOPICS[topic]["content"]))
    assert decision.decision == "approve"
    assert decision.coverage_rate == 1.0


def test_missing_goal_without_linked_issue_is_correctable():
    content = TOPICS["数学"]["content"]
    targets = [{"target": TARGETS[0], "status": "missing", "reason": "未讲解"},
               {"target": TARGETS[1], "status": "covered", "reason": "已讲解",
                "location": loc(content, "p000002")}]
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, targets=targets))
    assert caught.value.code == "TARGET_LINK_MISSING"
    assert caught.value.correctable


def test_coverage_issue_cannot_target_a_covered_goal():
    content = TOPICS["数学"]["content"]
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, issues=[issue(content, targets=[TARGETS[0]])]))
    assert caught.value.code == "COVERAGE_TARGET_INVALID"
    assert caught.value.correctable


def test_advisory_coverage_note_cannot_contradict_target_verdicts():
    content = TOPICS["数学"]["content"]
    advisory = issue(content, targets=[TARGETS[0]], blocking=False)
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, issues=[advisory]))
    assert caught.value.code == "COVERAGE_TARGET_INVALID"


def test_pass_dimension_with_blocking_issue_conflicts():
    content = TOPICS["数学"]["content"]
    output = build(content, issues=[issue(content, dimension="self_contained", rule="self_contained")])
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, output)
    assert caught.value.code == "DIMENSION_ISSUE_CONFLICT"
    assert caught.value.correctable


def test_failed_dimension_without_issue_conflicts():
    content = TOPICS["数学"]["content"]
    output = build(content, dims={"factual_evidence": "fail", "difficulty": "pass", "self_contained": "pass"},
                   score=0.5)
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, output)
    assert caught.value.code == "DIMENSION_ISSUE_CONFLICT"


def test_risk_score_must_match_factual_findings():
    content = TOPICS["数学"]["content"]
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, score=0.7))
    assert caught.value.code == "RISK_SCORE_CONFLICT"


def test_omitted_blocking_issues_is_never_correctable():
    content = TOPICS["数学"]["content"]
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, omitted=True))
    assert caught.value.code == "OMITTED_BLOCKING_ISSUES"
    assert not caught.value.correctable


def test_target_set_must_equal_frozen_goals():
    content = TOPICS["数学"]["content"]
    targets = [{"target": TARGETS[0], "status": "covered", "reason": "已讲解",
                "location": loc(content, "p000002")}]
    with pytest.raises(LectureReviewValidationError) as caught:
        validate(content, build(content, targets=targets))
    assert caught.value.code == "TARGET_SET_INCOMPLETE"


def test_derived_rate_is_the_only_total():
    content = TOPICS["数学"]["content"]
    targets = [{"target": TARGETS[0], "status": "missing", "reason": "未讲解"},
               {"target": TARGETS[1], "status": "covered", "reason": "已讲解",
                "location": loc(content, "p000002")}]
    output = build(content, targets=targets, issues=[issue(content, targets=[TARGETS[0]])])
    assert derived_coverage_rate(output.targets) == 0.5
    assert validate(content, output).coverage_rate == 0.5


def test_issue_identity_is_stable_and_versioned():
    first = issue_id_v2(run_id="r", resource_spec_id="s", lineage_id="l", step_id="step", ordinal=1)
    assert first == issue_id_v2(run_id="r", resource_spec_id="s", lineage_id="l", step_id="step", ordinal=1)
    assert first != issue_id_v2(run_id="r", resource_spec_id="s", lineage_id="l", step_id="step", ordinal=2)
    assert first.startswith("li2_")


def test_issue_rejects_target_links_outside_coverage():
    with pytest.raises(ValueError):
        LectureIssueV2.model_validate(issue("正文", dimension="self_contained", targets=[TARGETS[0]],
                                            paragraph="p000001", rule="self_contained"))
