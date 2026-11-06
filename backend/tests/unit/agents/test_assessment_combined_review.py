import copy

import pytest

from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
from app.agents.resource_workflows.learning_documents.reviewing.results import normalize_review_result
from app.agents.resource_agents.assessment import _assign_scores, render_assessment_markdown
from app.models.shared.persistence import canonical_hash
from app.models.shared.agent_contracts import AssessmentCombinedReviewV2
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.resource_reviews import approve, case, combined_output, questions, state_for


def test_public_maximum_twelve_questions_use_one_call_and_frozen_output_budget():
    sample = case("assessment.clean.12")
    gateway = ScriptedLLMGateway([combined_output(sample)])
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert gateway.calls[0]["options"].max_output_tokens == 16384
    assert result["review_result"]["decision"] == "approve"
    assert len(result["review_audit"]["resources"][0]["findings"]) == 12


@pytest.mark.parametrize("corrupt", ["missing", "duplicate", "unknown", "foreign_evidence", "missing_support", "short_rubric", "choice_rubric"])
def test_invalid_findings_never_approve_and_do_not_fall_back(corrupt):
    sample = case("assessment.clean.01")
    raw = combined_output(sample)
    if corrupt == "missing":
        raw["findings"].pop()
    elif corrupt == "duplicate":
        raw["findings"].append(copy.deepcopy(raw["findings"][0]))
    elif corrupt == "unknown":
        raw["findings"][0]["question_id"] = "unknown"
    elif corrupt == "foreign_evidence":
        raw["findings"][0]["supported_evidence_ids"] = ["foreign"]
    elif corrupt == "missing_support":
        raw["findings"][0]["supported_evidence_ids"] = []
    elif corrupt == "short_rubric":
        raw["findings"][4]["rubric_check"] = "not_applicable"
    else:
        raw["findings"][0]["rubric_check"] = "pass"
    gateway = ScriptedLLMGateway([raw])
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=gateway)
    assert len(gateway.calls) == 1
    assert result["review_result"]["decision"] == "human_review"
    assert result["generated_resources"][0].publication_status == "unpublished"


@pytest.mark.parametrize("field,value", [("scope_decision", "out_of_scope"), ("answer_check", "fail"), ("clarity_check", "fail"), ("rubric_check", "fail")])
def test_each_question_gate_overrides_approving_summary(field, value):
    sample = case("assessment.clean.01")
    raw = combined_output(sample)
    target = raw["findings"][4 if field == "rubric_check" else 2]  # Includes multiple-choice answers.
    target[field] = value
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=ScriptedLLMGateway([raw]))
    assert result["review_result"]["decision"] == "revise"
    assert result["review_audit"]["resources"][0]["findings"][4 if field == "rubric_check" else 2]["codes"]


def test_full_findings_are_not_limited_by_three_issue_summary():
    sample = case("assessment.clean.12")
    raw = combined_output(sample, failed_ids=[q["question_id"] for q in questions(sample)])
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=ScriptedLLMGateway([raw]))
    assert len(result["review_result"]["issues"]) == 3
    assert len(result["review_audit"]["resources"][0]["findings"]) == 12
    output = approve()
    output["issues"] = [{"code": "other", "severity": "critical", "description": "整卷关键问题"}]
    normalized = normalize_review_result(output=output, findings=result["review_audit"]["resources"][0]["findings"],
                                         resource_context=state_for(sample)["generated_resources"][0])
    assert normalized["issues"][0]["severity"] == "critical"


def test_budget_rejection_makes_zero_calls_without_switching_strategy():
    sample = case("assessment.clean.12")
    gateway = ScriptedLLMGateway([])
    result = review_node(state_for(sample, strategy="combined_v2", window=16384), llm_gateway=gateway)
    assert gateway.calls == []
    assert result["review_result"]["decision"] == "human_review"
    assert result["review_audit"]["resources"][0]["error_category"] == "input_budget"
    assert result["review_audit"]["summary"]["usage"]["total_tokens"] == 0


def test_internal_maximum_schema_supports_300_findings_but_not_301():
    raw = combined_output(case("assessment.clean.01"))
    raw["findings"] = [dict(raw["findings"][0], question_id=f"q-{i:03}") for i in range(1, 301)]
    assert len(AssessmentCombinedReviewV2.model_validate(raw).findings) == 300
    raw["findings"].append(dict(raw["findings"][0], question_id="q-301"))
    with pytest.raises(ValueError):
        AssessmentCombinedReviewV2.model_validate(raw)


def test_internal_fifty_node_package_is_explicitly_over_budget_without_truncation():
    sample = case("assessment.clean.01")
    package = sample["resource"]["assessment_payload"]
    blocks, rows = [], []
    for index in range(50):
        block = copy.deepcopy(package["node_blocks"][0])
        block["skill_node_id"] = f"internal-{index}"
        for field in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions"):
            for question in block[field]:
                question["question_id"] = f"q-{len(rows)+1:03}"
                question["knowledge_point_tags"] = [block["skill_node_id"]]
                rows.append(question)
        blocks.append(block)
    _assign_scores(rows)
    package["node_blocks"] = blocks
    package["payload_hash"] = canonical_hash({k: v for k, v in package.items() if k != "payload_hash"})
    sample["target_skill_nodes"] = [b["skill_node_id"] for b in blocks]
    sample["resource"]["knowledge_points"] = sample["target_skill_nodes"]
    sample["resource"]["content_text"] = render_assessment_markdown(package)
    gateway = ScriptedLLMGateway([])
    output = review_node(state_for(sample, strategy="combined_v2", window=65536), llm_gateway=gateway)
    assert gateway.calls == []
    assert output["review_audit"]["resources"][0]["error_category"] == "input_budget"
    assert len(questions(sample)) == 300


def test_question_cannot_borrow_another_questions_evidence_in_same_resource():
    sample = case("assessment.clean.12")
    raw = combined_output(sample)
    raw["findings"][0]["supported_evidence_ids"] = [sample["evidence"][1]["evidence_id"]]
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=ScriptedLLMGateway([raw]))
    assert result["review_result"]["decision"] == "human_review"


def test_invalid_summary_target_stays_closed_and_keeps_completed_call():
    sample = case("assessment.clean.01")
    raw = combined_output(sample)
    raw["summary"].update(decision="revise", revision_instructions=[{
        "issue_codes": ["structure_quality"], "target_resource_type": "讲义", "action": "PRIVATE_TEXT"}])
    result = review_node(state_for(sample, strategy="combined_v2"), llm_gateway=ScriptedLLMGateway([raw]))
    assert result["review_result"]["decision"] == "human_review"
    assert result["review_audit"]["calls"][0]["status"] == "invalid_result"
    assert "PRIVATE_TEXT" not in str(result["review_result"])
