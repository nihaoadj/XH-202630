from app.agents.resource_workflows.learning_documents.specialized_reviews.assessment_scope import (
    review_assessment_scope,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.llm import LLMCallContext
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def _resource():
    return LearningResource(
        resource_id="assessment-scope", resource_type="分阶测试题", difficulty="初级",
        content_text="# 脱敏测评\n", knowledge_points=["skill-search"], source_refs=[],
        assessment_payload={
            "schema_version": "2.0", "node_blocks": [{
                "skill_node_id": "skill-search", "skill_node_name": "受控检索",
                "single_choice_questions": [{
                    "question_id": "q-001", "question_type": "single_choice", "difficulty_stage": "基础",
                    "stem": "如何使用冻结证据？", "options": [], "answer_option_ids": ["A"],
                    "knowledge_point_tags": ["skill-search"], "evidence_ids": ["ev-scope"],
                }], "multiple_choice_questions": [], "short_answer_questions": [],
            }],
        },
    )


def test_scope_review_accepts_only_per_question_allowed_evidence():
    outcome = review_assessment_scope(
        resource=_resource(), evidence=[make_evidence(evidence_id="ev-scope")],
        target_skill_nodes=["skill-search"],
        llm_gateway=ScriptedLLMGateway([{"findings": [{
            "question_id": "q-001", "decision": "in_scope", "reason": "符合节点范围。",
            "supported_evidence_ids": ["ev-scope"],
        }]}]),
        context=LLMCallContext(run_id="run-scope", step_id="step-scope", node_name="test", schema_name="test"),
    )

    assert outcome.passed is True
    assert outcome.issues == []


def test_scope_review_returns_targeted_revision_for_out_of_scope_question():
    outcome = review_assessment_scope(
        resource=_resource(), evidence=[make_evidence(evidence_id="ev-scope")],
        target_skill_nodes=["skill-search"],
        llm_gateway=ScriptedLLMGateway([{"findings": [{
            "question_id": "q-001", "decision": "out_of_scope", "reason": "题干考查了其他能力节点。",
            "supported_evidence_ids": [],
        }]}]),
        context=LLMCallContext(run_id="run-scope", step_id="step-scope", node_name="test", schema_name="test"),
    )

    assert outcome.passed is False
    assert outcome.issues[0]["code"] == "coverage_gap"
    assert outcome.revision_instructions[0]["target_resource_type"] == "分阶测试题"
