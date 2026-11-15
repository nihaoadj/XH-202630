"""Review evidence lists are bounded by question whitelists, not fixed counts."""
import pytest
from app.models.reviews.resource_review import ResourceFindingV1
from app.models.reviews.review_audit import ReviewFindingV1
from app.models.shared.agent_contracts import AssessmentScopeFindingV1, AssessmentQuestionReviewV2

@pytest.mark.parametrize("schema", [ResourceFindingV1, ReviewFindingV1, AssessmentScopeFindingV1, AssessmentQuestionReviewV2])
def test_evidence_has_no_fixed_count_and_is_stably_deduplicated(schema):
    payload = dict(question_id="q-001", skill_node_id="rag_basics", reason="supported",
                   scope_decision="in_scope", answer_check="pass", clarity_check="pass",
                   rubric_check="not_applicable", decision="in_scope",
                   supported_evidence_ids=["e1", "e2", "e1", "e3", "e4"])
    result = schema.model_validate({k:v for k,v in payload.items() if k in schema.model_fields})
    assert result.supported_evidence_ids == ["e1", "e2", "e3", "e4"]


@pytest.mark.parametrize("ids,accepted", [(["e1", "e2", "e1"], True), (["e1", "foreign"], False), ([], False)])
def test_question_whitelist_still_applies_in_both_review_paths(ids, accepted):
    from types import SimpleNamespace
    from app.agents.resource_workflows.learning_documents.specialized_reviews.assessment_scope import validate_assessment_findings
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.assessment import AssessmentAdapter
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.validation import ValidationError

    question = dict(question_id="q-001", question_type="single_choice", skill_node_id="rag_basics", evidence_ids=["e1", "e2"])
    finding = dict(question_id="q-001", skill_node_id="rag_basics", reason="supported", scope_decision="in_scope",
                   answer_check="pass", clarity_check="pass", rubric_check="not_applicable", supported_evidence_ids=ids)
    def legacy():
        return validate_assessment_findings(findings=[finding], questions=[question],
            allowed_evidence_by_question={"q-001": {"e1", "e2"}}, combined=True)
    def generic():
        material = SimpleNamespace(structured_payload={"node_blocks": [{"single_choice_questions": [question]}]})
        output = SimpleNamespace(findings=[ResourceFindingV1(**finding)], issues=[])
        return AssessmentAdapter().validate_findings(output=output, material=material)
    if accepted:
        assert legacy()[0]["supported_evidence_ids"] == ["e1", "e2"]
        generic()
    else:
        with pytest.raises(ValueError):
            legacy()
        with pytest.raises(ValidationError):
            generic()
