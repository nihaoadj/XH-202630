"""T44 resource adapters: six types, dual hash and version-bound locations."""

import copy
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.assessment import (
    AssessmentAdapter,
    assessment_comparison_projection,
    assessment_questions,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import (
    comparison_text_hash,
    text_hash,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.case_study import CaseStudyAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.checklist import (
    ChecklistAdapter,
    checklist_comparison_projection,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.correction_package import CorrectionPackageAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.lecture import LectureAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.practice import (
    PracticeAdapter,
    practice_comparison_projection,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import (
    ValidationError,
    validate_resource_review,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceLocationV1,
    ResourceReviewBindingV1,
    ResourceReviewInitialV1,
)
from tests.fakes.resource_reviews import case


def prose_resource(text: str, resource_type="讲义") -> SimpleNamespace:
    return SimpleNamespace(
        resource_type=resource_type, content_text=text, difficulty="初级",
        resource_id="res-1", resource_spec_id="spec-1", resource_family_id="fam-1",
        version=1, parent_resource_id=None, practice_guide_payload=None,
        assessment_payload=None, review_practice_payload=None, knowledge_points=["目标一"])


def evidence():
    return []


TARGETS = ["目标一"]


def test_prose_adapters_build_paragraph_index_and_dual_hash():
    text = "## 标题\n第一段内容。\n\n第二段内容。"
    for adapter in (LectureAdapter(), CaseStudyAdapter(), CorrectionPackageAdapter()):
        material = adapter.build_material(resource=prose_resource(text), evidence=evidence(),
                                          spec={}, targets=TARGETS)
        assert material.artifact_exact_hash != material.comparison_hash
        assert material.text_exact_hash == text_hash(text)
        assert material.comparison_hash == comparison_text_hash(text)
        assert material.structured_payload is None
        assert "p000002" in material.index.paragraph_ids
        assert material.projection_consistent is True


def test_practice_adapter_replaces_only_step_ids_in_comparison_projection():
    sample = case("practice.clean.01")
    resource = LearningResource.model_validate(sample["resource"])
    adapter = PracticeAdapter()
    material = adapter.build_material(resource=resource, evidence=evidence(),
                                      spec={}, targets=TARGETS)
    assert material.structured_payload is not None
    projection = material.comparison_projection
    steps = projection["practice"]["steps"]
    assert all(step["step_id"] == "MECH_STEP" for step in steps)
    # exact hash changes when the mechanical id changes, comparison hash must not.
    assert material.artifact_exact_hash != material.comparison_hash
    # all non-mechanical fields are preserved in the projection
    assert projection["practice"]["steps"][0]["instruction_text"] == \
        resource.practice_guide_payload["practice"]["steps"][0]["instruction_text"]


def test_practice_mechanical_id_only_keeps_comparison_hash_stable():
    sample = case("practice.clean.01")
    resource = LearningResource.model_validate(sample["resource"])
    adapter = PracticeAdapter()
    original = adapter.build_material(resource=resource, evidence=evidence(), spec={}, targets=TARGETS)
    changed_payload = copy.deepcopy(resource.practice_guide_payload)
    for index, step in enumerate(changed_payload["practice"]["steps"]):
        step["step_id"] = f"step-{index:03d}"
    changed = SimpleNamespace(**{**resource.model_dump(mode="python"),
                                 "practice_guide_payload": changed_payload})
    rebuit = adapter.build_material(resource=changed, evidence=evidence(), spec={}, targets=TARGETS)
    assert rebuit.artifact_exact_hash != original.artifact_exact_hash
    assert rebuit.comparison_hash == original.comparison_hash


def test_assessment_adapter_replaces_only_question_ids():
    sample = case("assessment.clean.01")
    resource = LearningResource.model_validate(sample["resource"])
    adapter = AssessmentAdapter()
    material = adapter.build_material(resource=resource, evidence=evidence(), spec={}, targets=TARGETS)
    questions = assessment_questions(resource.assessment_payload)
    assert questions
    assert material.index.unit_ids == frozenset(q["question_id"] for q in questions)
    projection = material.comparison_projection
    for block in projection["node_blocks"]:
        for field in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions"):
            for question in block[field]:
                assert question["question_id"] == "MECH_Q"


def test_structured_adapter_missing_payload_is_projection_inconsistent():
    resource = prose_resource("## 准备阶段\n内容", resource_type="实操指南")
    resource.practice_guide_payload = None
    material = PracticeAdapter().build_material(resource=resource, evidence=evidence(), spec={}, targets=TARGETS)
    assert material.projection_consistent is False
    assert material.structured_payload is None


def test_checklist_comparison_projection_replaces_question_ids():
    payload = {"node_blocks": [{"skill_node_id": "n1", "recall_questions": [
        {"question_id": "q1", "prompt": "p"}, {"question_id": "q2", "prompt": "p2"}]}]}
    projection = checklist_comparison_projection(payload)
    assert all(q["question_id"] == "MECH_Q" for q in projection["node_blocks"][0]["recall_questions"])
    assert projection["node_blocks"][0]["skill_node_id"] == "n1"


# --------------------------------------------------------------------------- #
# validate_resource_review via the lecture adapter
# --------------------------------------------------------------------------- #

def _lecture_material(text="## 标题\n讲解内容。"):
    return LectureAdapter().build_material(resource=prose_resource(text), evidence=evidence(),
                                           spec={}, targets=TARGETS)


def _binding(material):
    return ResourceReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="fam-1", resource_id="res-1",
        resource_type="讲义", version=1, text_exact_hash=material.text_exact_hash,
        structured_payload_hash=None, artifact_exact_hash=material.artifact_exact_hash,
        comparison_hash=material.comparison_hash, evidence_snapshot_hash=text_hash("evidence"),
        policy_hash=text_hash("policy"))


def _output(material, *, issues=()):
    return ResourceReviewInitialV1.model_validate({
        "binding": _binding(material).model_dump(mode="json"),
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": t, "status": "covered", "reason": "已讲解",
                     "location": {"kind": "root"}} for t in TARGETS],
        "hallucination_score": 0.0,
        "issues": [issue.model_dump(mode="json") for issue in issues],
        "omitted_blocking_issues": False,
    })


def test_validate_rejects_out_of_bounds_location():
    material = _lecture_material()
    bad = ResourceIssueV1.model_validate({
        "issue_id": "tmp-1", "code": "structure_quality", "severity": "high", "blocking": True,
        "blocking_rule": "self_contained", "dimension": "self_contained",
        "location": {"kind": "paragraph", "paragraph_id": "p999999"},
        "impact": "x", "requirement": "y", "acceptance": "z", "criteria_version": 1,
        "path": "reorganize_existing", "teaching_rule_id": "self_contained",
        "executability": "executable", "rationale": "r",
    })
    with pytest.raises(ValidationError) as exc:
        validate_resource_review(output=_output(material, issues=[bad]), binding=_binding(material),
                                 material=material, adapter=LectureAdapter(),
                                 previous_comparison_hash=None)
    assert exc.value.code == "LOCATION_OUT_OF_BOUNDS"


def test_validate_rejects_model_declared_program_origin():
    material = _lecture_material()
    bad = ResourceIssueV1.model_validate({
        "issue_id": "tmp-1", "origin": "program_gate", "code": "structure_quality",
        "severity": "high", "blocking": True, "blocking_rule": "self_contained",
        "dimension": "self_contained", "location": {"kind": "root"},
        "impact": "x", "requirement": "y", "acceptance": "z", "criteria_version": 1,
        "path": "reorganize_existing", "executability": "executable", "rationale": "r",
    })
    with pytest.raises(ValidationError) as exc:
        validate_resource_review(output=_output(material, issues=[bad]), binding=_binding(material),
                                 material=material, adapter=LectureAdapter(),
                                 previous_comparison_hash=None)
    assert exc.value.code == "ORIGIN_INVALID"


def test_validate_rejects_coverage_issue_on_covered_target():
    material = _lecture_material()
    bad = ResourceIssueV1.model_validate({
        "issue_id": "tmp-1", "code": "coverage_gap", "severity": "high", "blocking": True,
        "blocking_rule": "target_coverage", "dimension": "coverage",
        "affected_target_ids": ["目标一"], "location": {"kind": "root"},
        "impact": "x", "requirement": "y", "acceptance": "z", "criteria_version": 1,
        "path": "reorganize_existing", "teaching_rule_id": "target_coverage",
        "executability": "executable", "rationale": "r",
    })
    with pytest.raises(ValidationError) as exc:
        validate_resource_review(output=_output(material, issues=[bad]), binding=_binding(material),
                                 material=material, adapter=LectureAdapter(),
                                 previous_comparison_hash=None)
    assert exc.value.code == "COVERAGE_TARGET_INVALID"


def test_assessment_findings_must_map_bidirectionally():
    sample = case("assessment.clean.01")
    resource = LearningResource.model_validate(sample["resource"])
    adapter = AssessmentAdapter()
    material = adapter.build_material(resource=resource, evidence=evidence(), spec={}, targets=TARGETS)
    binding = ResourceReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="fam-1", resource_id="res-1",
        resource_type="分阶测试题", version=1, text_exact_hash=material.text_exact_hash,
        structured_payload_hash=material.structured_payload_hash,
        artifact_exact_hash=material.artifact_exact_hash, comparison_hash=material.comparison_hash,
        evidence_snapshot_hash=text_hash("evidence"), policy_hash=text_hash("policy"))
    questions = assessment_questions(resource.assessment_payload)
    # All questions pass -> no failed keys -> no issues allowed.
    findings = [{"question_id": q["question_id"], "scope_decision": "in_scope",
                 "supported_evidence_ids": (q.get("evidence_ids") or [])[:1],
                 "answer_check": "pass", "clarity_check": "pass",
                 "rubric_check": "not_applicable" if q["question_type"] in {"single_choice", "multiple_choice"} else "pass",
                 "reason": "ok"} for q in questions]
    output = ResourceReviewInitialV1.model_validate({
        "binding": binding.model_dump(mode="json"),
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": t, "status": "covered", "reason": "已讲解",
                     "location": {"kind": "root"}} for t in TARGETS],
        "hallucination_score": 0.0, "issues": [], "findings": findings,
        "omitted_blocking_issues": False,
    })
    outcome = validate_resource_review(output=output, binding=binding, material=material,
                                       adapter=adapter, previous_comparison_hash=None)
    assert outcome.dimensions_pass is True
