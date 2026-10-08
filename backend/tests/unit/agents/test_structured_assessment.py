import json
import pytest

from app.agents.resource_agents.assessment import AssessmentAgent, _assign_scores
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.models.shared.agent_contracts import AssessmentNodeBlockV2, ResourceGenerationContext
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway
from app.core.security.errors import ApplicationError


def _block(node_id: str, evidence_id: str):
    def choice(local_id, question_type, answer):
        return {"local_id": local_id, "question_type": question_type, "stem": f"{node_id} 的题目",
                "options": [{"option_id": item, "text": f"选项 {item}"} for item in "ABCD"],
                "answer_option_ids": answer, "knowledge_point_tags": [node_id], "evidence_ids": [evidence_id]}
    def short(local_id):
        return {"local_id": local_id, "question_type": "short_answer", "stem": f"解释 {node_id}",
                "reference_answer": "依据冻结证据说明。", "rubric": [{"criterion": "说明依据", "points": 1}, {"criterion": "说明边界", "points": 1}],
                "knowledge_point_tags": [node_id], "evidence_ids": [evidence_id]}
    return {"schema_version": "2.0", "skill_node_id": node_id, "skill_node_name": node_id,
            "single_choice_questions": [choice("single-1", "single_choice", ["A"]), choice("single-2", "single_choice", ["B"])],
            "multiple_choice_questions": [choice("multiple-1", "multiple_choice", ["A", "C"]), choice("multiple-2", "multiple_choice", ["B", "D"])],
            "short_answer_questions": [short("short-1"), short("short-2")]}


def test_single_node_assessment_uses_the_configured_question_scores():
    rows = [
        {"question_id": question_id, "question_type": question_type}
        for question_id, question_type in (
            ("q-001", "single_choice"), ("q-002", "single_choice"),
            ("q-003", "multiple_choice"), ("q-004", "multiple_choice"),
            ("q-005", "short_answer"), ("q-006", "short_answer"),
        )
    ]

    _assign_scores(rows)

    assert [item["max_score"] for item in rows] == [15.0, 15.0, 20.0, 20.0, 15.0, 15.0]


def test_assessment_calls_once_per_target_node_and_renders_without_answers():
    evidence = make_evidence(evidence_id="ev-structured-assessment")
    spec = build_resource_specs(run_id="run-structured", resource_types=["分阶测试题"], topic="检索",
        difficulty="中级", learning_plan={}, evidence=[evidence], target_skill_nodes=["node-a", "node-b"])[0]
    context = ResourceGenerationContext(run_id="run-structured", batch_id="batch-structured", topic="检索", evidence=[evidence])
    gateway = ScriptedLLMGateway([_block("node-a", evidence.evidence_id), _block("node-b", evidence.evidence_id)])

    artifact = AssessmentAgent().generate(spec, context, llm_gateway=gateway)

    package = artifact.artifact_data["assessment_package"]
    assert len(gateway.calls) == 2
    assert [item["skill_node_id"] for item in package["node_blocks"]] == ["node-a", "node-b"]
    questions = [item for block in package["node_blocks"]
                 for field_name in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions")
                 for item in block[field_name]]
    assert len(questions) == 12
    assert sum(item["max_score"] for item in questions) == 100
    assert {item["difficulty_stage"] for item in package["node_blocks"][0]["single_choice_questions"]} == {"基础"}
    assert len(package["node_blocks"][0]["multiple_choice_questions"]) == 2
    assert package["node_blocks"][0]["multiple_choice_questions"][0]["difficulty_stage"] == "进阶"
    assert {item["difficulty_stage"] for item in package["node_blocks"][0]["short_answer_questions"]} == {"挑战"}
    assert "参考答案" not in artifact.content_text
    assert "### 单选题" in artifact.content_text and "### 多选题" in artifact.content_text and "### 问答题" in artifact.content_text


def test_assessment_revision_prompt_includes_scoped_reviewer_feedback():
    evidence = make_evidence(evidence_id="ev-assessment-revision")
    spec = build_resource_specs(run_id="run-assessment-revision", resource_types=["分阶测试题"], topic="检索",
        difficulty="中级", learning_plan={}, evidence=[evidence], target_skill_nodes=["node-a"])[0]
    context = ResourceGenerationContext(
        run_id="run-assessment-revision", batch_id="batch-assessment-revision", topic="检索", evidence=[evidence],
        generation_attempt=2,
        constraints={"revision_feedback": {"issues": [{"code": "coverage_gap", "knowledge_point": "node-a", "description": "q-001 越界"}]}},
    )

    messages = AssessmentAgent()._messages(spec, context, "node-a")
    payload = json.loads(messages[-1].content)

    assert payload["revision_feedback"]["issues"][0]["description"] == "q-001 越界"
    assert payload["server_assigned_question_ids_for_this_node"] == ["q-001", "q-002", "q-003", "q-004", "q-005", "q-006"]
    assert payload["revision_feedback"]["rejected_question_ids"] == ["q-001"]


def test_assessment_prompt_receives_history_and_rejects_duplicate_stem():
    evidence = make_evidence(evidence_id="ev-history")
    spec = build_resource_specs(run_id="run-history", resource_types=["分阶测试题"], topic="检索",
        difficulty="中级", learning_plan={}, evidence=[evidence], target_skill_nodes=["node-a"])[0]
    context = ResourceGenerationContext(
        run_id="run-history", batch_id="batch-history", topic="检索", evidence=[evidence],
        constraints={"historical_assessment_questions": [{"skill_node_id": "node-a", "question_text": "node-a 的题目"}]},
    )
    payload = json.loads(AssessmentAgent()._messages(spec, context, "node-a")[-1].content)
    assert payload["historical_assessment_questions"][0]["question_text"] == "node-a 的题目"
    with pytest.raises(ApplicationError):
        AssessmentAgent._validate_node(
            AssessmentNodeBlockV2.model_validate(_block("node-a", evidence.evidence_id)), spec, "node-a", context,
        )
