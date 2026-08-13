import pytest
from pydantic import ValidationError

from app.models.agent_contracts import (
    DiagnosisLLMOutput,
    GeneratedResourceBatch,
    PlannerLLMOutput,
    ReviewLLMOutput,
)


def test_diagnosis_output_is_strict_and_forbids_extra_fields():
    output = DiagnosisLLMOutput(
        ability_tags=["检索"],
        weak_points=["重排"],
        recommended_difficulty="中级",
        suggestion="先补齐基础。",
    )
    assert output.recommended_difficulty == "中级"

    with pytest.raises(ValidationError):
        DiagnosisLLMOutput.model_validate({**output.model_dump(), "unknown": True})


def test_planner_output_rejects_duplicate_path_order():
    with pytest.raises(ValidationError):
        PlannerLLMOutput.model_validate({
            "learning_path": [
                {"order": 1, "topic": "A", "reason": "先学习 A"},
                {"order": 1, "topic": "B", "reason": "再学习 B"},
            ],
            "skip_points": [],
            "remedial_points": [],
            "challenge_points": [],
            "resource_requirements": {},
            "decision_reason": "测试",
        })


def test_generated_resource_batch_requires_unique_types_and_content():
    with pytest.raises(ValidationError):
        GeneratedResourceBatch.model_validate({
            "resources": [
                {
                    "resource_type": "讲义",
                    "difficulty": "中级",
                    "content_text": "内容一",
                    "knowledge_points": ["A"],
                },
                {
                    "resource_type": "讲义",
                    "difficulty": "中级",
                    "content_text": "内容二",
                    "knowledge_points": ["B"],
                },
            ]
        })


def test_review_output_uses_structured_issues_and_instructions():
    valid = ReviewLLMOutput(
        decision="revise",
        hallucination_score=0.2,
        issues=[{
            "code": "coverage_gap",
            "severity": "medium",
            "resource_type": "讲义",
            "knowledge_point": None,
            "description": "缺少边界条件",
        }],
        difficulty_match=True,
        coverage_rate=0.8,
        suggestion="补充边界条件。",
        revision_instructions=[{
            "issue_codes": ["coverage_gap"],
            "target_resource_type": "讲义",
            "action": "增加失败示例",
            "priority": 1,
        }],
    )
    assert valid.decision == "revise"

    with pytest.raises(ValidationError):
        ReviewLLMOutput.model_validate({**valid.model_dump(), "passed": True})
    human_review = ReviewLLMOutput.model_validate(
        {
            **valid.model_dump(),
            "decision": "human_review",
            "revision_instructions": [],
        }
    )
    assert human_review.decision == "human_review"
