"""Versioned ledger transitions, independent of Provider behavior."""

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.lecture_contract import text_hash
from app.agents.resource_workflows.learning_documents.reviewing.lecture_ledger import append_lecture_observation
from app.models.reviews.lecture_review import LectureLedgerV1, LectureResolutionV1, LectureLocationV1
from tests.unit.agents.test_lecture_review_contract import make_issue, make_output


def append(output, *, previous=None, content="题目", old_content=None, step="step1", parent=None):
    return append_lecture_observation(previous=previous, binding=output.binding, step_id=step,
        output=output, content=content, previous_content=old_content, parent_resource_id=parent,
        targets=["target"], evidence_hashes={}, teaching_rule_ids={"exercise"})


def initial():
    output = make_output(issues=[make_issue("temporary")])
    return output.model_copy(update={"dimensions": output.dimensions.model_copy(update={"self_contained": "fail"})})


def test_server_ids_and_same_step_replay():
    output = initial()
    ledger = append(output)
    assert ledger.issues[0].issue.issue_id.startswith("li_")
    assert ledger.issues[0].issue.issue_id != "temporary"
    assert append(output, previous=ledger) == ledger
    with pytest.raises(ValueError, match="replay conflict"):
        append(output.model_copy(update={"hallucination_score": 0.1}), previous=ledger)


def test_unchanged_false_positive_retains_history_and_exact_parent():
    ledger = append(initial())
    resolution = LectureResolutionV1(issue_id=ledger.issues[0].issue.issue_id,
        result="false_positive", reason="旧版已有作答材料",
        previous_location=LectureLocationV1(paragraph_id="p000001", quote="题目"))
    output = make_output(resolutions=[resolution])
    output = output.model_copy(update={"binding": output.binding.model_copy(update={"version": 3, "resource_id": "r3"})})
    updated = append(output, previous=ledger, old_content="题目", step="step2", parent="resource")
    assert len(updated.observations) == 2
    assert updated.issues[0].status == "closed"
    assert ledger.issues[0].status == "open"
    assert updated.observations[-1].unchanged
    assert updated.observations[-1].consecutive_unchanged == 1
    assert updated.observations[-1].output.resolutions[0] == resolution
    with pytest.raises(ValueError, match="parent"):
        append(output, previous=ledger, old_content="题目", step="step2", parent="other")
    with pytest.raises(ValueError, match="parent"):
        append(output, previous=ledger, old_content="被替换的旧正文", step="step2", parent="resource")


def test_cross_resource_and_changed_hash_are_rejected():
    ledger = append(initial())
    output = make_output(content="新题目")
    output = output.model_copy(update={"binding": output.binding.model_copy(update={
        "version": 3, "resource_id": "r3", "resource_spec_id": "other", "content_hash": text_hash("新题目")})})
    with pytest.raises(ValueError, match="resource"):
        append(output, previous=ledger, content="新题目", old_content="题目", step="step2", parent="resource")


def test_reloaded_ledger_cannot_close_an_issue_without_observation():
    data = append(initial()).model_dump(mode="json")
    data["issues"][0]["status"] = "closed"
    with pytest.raises(ValueError, match="disagrees with observations"):
        LectureLedgerV1.model_validate(data)


def test_reloaded_ledger_rejects_rewritten_requirements():
    data = append(initial()).model_dump(mode="json")
    data["issues"][0]["issue"]["acceptance"] = "降低验收要求"
    with pytest.raises(ValueError, match="disagrees with observations"):
        LectureLedgerV1.model_validate(data)
