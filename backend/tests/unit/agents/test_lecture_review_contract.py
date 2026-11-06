"""Tests for the isolated T38 contract, not an end-to-end review gate."""

import math

import pytest
from pydantic import ValidationError

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import (
    comparison_hash, issue_id, text_hash, validate_lecture_review,
)
from app.models.reviews.lecture_review import (
    LectureDimensionsV1, LectureEvidenceRefV1, LectureIssueV1, LectureLocationV1,
    LectureReopenV1, LectureResolutionV1, LectureReviewBindingV1, LectureReviewOutputV1,
    LectureTargetCoverageV1,
)


def make_issue(issue="old", **changes):
    values = dict(issue_id=issue, code="missing_input", severity="high", blocking=True,
                  blocking_rule="required_input", dimension="self_contained",
                  location=LectureLocationV1(paragraph_id="p000001", quote="题目"),
                  impact="无法作答", requirement="补充名次", acceptance="两路名次齐全",
                  criteria_version=1, path="reorganize_existing", teaching_rule_id="exercise",
                  executability="executable", rationale="已有材料可供整理")
    values.update(changes)
    return LectureIssueV1(**values)


def make_output(content="题目", **changes):
    binding = LectureReviewBindingV1(run_id="run", resource_spec_id="spec", lineage_id="lineage",
                                     resource_id="resource", version=2, content_hash=text_hash(content),
                                     evidence_snapshot_hash="a" * 64, policy_hash="b" * 64)
    values = dict(binding=binding,
                  dimensions=LectureDimensionsV1(factual_evidence="pass", coverage="pass", difficulty="pass", self_contained="pass"),
                  targets=[LectureTargetCoverageV1(target="target", status="covered")],
                  hallucination_score=0.0, issues=[], resolutions=[], omitted_blocking_issues=False)
    values.update(changes)
    return LectureReviewOutputV1(**values)


def check(output, *, content="题目", previous_content=None, old_open=(), old_closed=(), **kwargs):
    return validate_lecture_review(output=output, binding=output.binding, content=content,
                                   previous_content=previous_content, targets=["target"], evidence_hashes={},
                                   teaching_rule_ids={"exercise"}, old_open=old_open, old_closed=old_closed,
                                   **kwargs)


def test_unchanged_false_positive_can_close_but_fixed_cannot():
    old = make_issue()
    location = LectureLocationV1(paragraph_id="p000001", quote="题目")
    false_positive = LectureResolutionV1(issue_id="old", result="false_positive", reason="原文已有", previous_location=location)
    assert check(make_output(resolutions=[false_positive]), previous_content="题目", old_open=(old,)).decision == "approve"
    fixed = LectureResolutionV1(issue_id="old", result="fixed", reason="已修复", current_location=location)
    with pytest.raises(ValueError, match="unchanged"):
        check(make_output(resolutions=[fixed]), previous_content="题目", old_open=(old,))


def test_partial_fix_requires_every_old_id_and_new_defects_block():
    first, second = make_issue("first"), make_issue("second")
    loc = LectureLocationV1(paragraph_id="p000001", quote="题目")
    fixed = LectureResolutionV1(issue_id="first", result="fixed", reason="名次已提供", current_location=loc)
    still = LectureResolutionV1(issue_id="second", result="still_open", reason="仍缺", current_location=loc)
    dimensions = LectureDimensionsV1(factual_evidence="pass", coverage="pass", difficulty="pass", self_contained="fail")
    result = check(make_output(content="题目修改", dimensions=dimensions, resolutions=[fixed, still]),
                   content="题目修改", previous_content="题目", old_open=(first, second))
    assert result.decision == "revise"
    assert [item.issue_id for item in result.open_issues] == ["second"]
    with pytest.raises(ValueError, match="incomplete"):
        check(make_output(content="题目修改", resolutions=[fixed]), content="题目修改", previous_content="题目", old_open=(first, second))


def test_unverifiable_and_no_progress_never_close():
    old = make_issue()
    resolution = LectureResolutionV1(issue_id="old", result="unverifiable", reason="缺证据")
    dimensions = LectureDimensionsV1(factual_evidence="pass", coverage="pass", difficulty="pass", self_contained="fail")
    output = make_output(dimensions=dimensions, resolutions=[resolution])
    assert check(output, previous_content="题目", old_open=(old,)).decision == "revise"
    assert check(output, previous_content="题目", old_open=(old,), consecutive_unchanged=1).decision == "human_review"


def test_evidence_scope_location_and_hash_are_checked():
    ref = LectureEvidenceRefV1(evidence_id="unknown", excerpt_hash="c" * 64)
    issue = make_issue("new", evidence_refs=[ref])
    dims = LectureDimensionsV1(factual_evidence="pass", coverage="pass", difficulty="pass", self_contained="fail")
    with pytest.raises(ValueError, match="frozen snapshot"):
        check(make_output(dimensions=dims, issues=[issue]))
    output = make_output()
    with pytest.raises(ValueError, match="content hash"):
        check(output, content="other")


def test_false_positive_does_not_clear_new_factual_defect():
    old = make_issue()
    loc = LectureLocationV1(paragraph_id="p000001", quote="题目")
    resolution = LectureResolutionV1(issue_id="old", result="false_positive", reason="旧版已经提供", previous_location=loc)
    factual = make_issue("new-fact", code="factual_risk", dimension="factual_evidence",
                         path="remove_or_narrow", requirement="删除无依据能力断言")
    dims = LectureDimensionsV1(factual_evidence="fail", coverage="pass", difficulty="pass", self_contained="pass")
    result = check(make_output(dimensions=dims, hallucination_score=0.2, issues=[factual], resolutions=[resolution]),
                   previous_content="题目", old_open=(old,))
    assert result.decision == "revise"
    assert [item.issue_id for item in result.open_issues] == ["new-fact"]


def test_reopen_requires_known_closed_id_and_current_location():
    old = make_issue()
    location = LectureLocationV1(paragraph_id="p000001", quote="题目")
    reopened = LectureReopenV1(issue_id="old", current_location=location, reason="缺陷再次出现")
    dims = LectureDimensionsV1(factual_evidence="pass", coverage="pass", difficulty="pass", self_contained="fail")
    result = check(make_output(dimensions=dims, reopen=[reopened]), previous_content="旧题目", old_closed=(old,))
    assert result.decision == "revise"
    with pytest.raises(ValueError, match="invalid reopened"):
        check(make_output(dimensions=dims, reopen=[reopened]), previous_content="旧题目")


@pytest.mark.parametrize("score", [math.nan, math.inf, -math.inf, -0.1, 1.1])
def test_risk_rejects_non_finite_and_out_of_range(score):
    with pytest.raises(ValidationError):
        make_output(hallucination_score=score)


def test_risk_boundary_and_frozen_targets():
    assert check(make_output(hallucination_score=0.199999)).decision == "approve"
    with pytest.raises(ValueError, match="risk score"):
        check(make_output(hallucination_score=0.2))
    with pytest.raises(ValueError, match="target coverage"):
        check(make_output(targets=[LectureTargetCoverageV1(target="other", status="covered")]))


def test_identity_is_stable_and_scoped_and_comparison_only_normalizes_crlf():
    first = issue_id(run_id="r", resource_spec_id="a", lineage_id="l", step_id="s", ordinal=1)
    assert first == issue_id(run_id="r", resource_spec_id="a", lineage_id="l", step_id="s", ordinal=1)
    assert first != issue_id(run_id="r", resource_spec_id="b", lineage_id="l", step_id="s", ordinal=1)
    assert comparison_hash("a\r\nb") == comparison_hash("a\nb")
    assert comparison_hash("a b") != comparison_hash("a  b")


def test_heading_paths_follow_server_markdown_and_ignore_code_fences():
    from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import paragraph_heading_paths
    content = "# Topic\nintro\n```python\n# code comment\n```\n## Exercise\nquestion"
    paths = paragraph_heading_paths(content)
    assert paths["p000004"] == ["Topic"]
    assert paths["p000007"] == ["Topic", "Exercise"]


def test_required_risk_cannot_be_omitted_or_defaulted():
    payload = make_output().model_dump(mode="json")
    del payload["hallucination_score"]
    with pytest.raises(ValidationError):
        LectureReviewOutputV1.model_validate(payload)


def test_high_severity_optional_and_evidence_free_technical_additions_fail():
    with pytest.raises(ValidationError, match="must block"):
        make_issue(blocking=False)
    with pytest.raises(ValidationError, match="frozen evidence"):
        make_issue(path="add_from_evidence")
