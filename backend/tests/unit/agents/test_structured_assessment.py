import json

from app.agents.resource_agents.assessment import AssessmentAgent
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.models.shared.agent_contracts import ResourceGenerationContext
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


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
            "multiple_choice_questions": [choice("multiple-1", "multiple_choice", ["A", "C"])],
            "short_answer_questions": [short("short-1"), short("short-2")]}


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
    assert len(questions) == 10
    assert sum(item["max_score"] for item in questions) == 100
    assert {item["difficulty_stage"] for item in package["node_blocks"][0]["single_choice_questions"]} == {"基础"}
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
    assert payload["server_assigned_question_ids_for_this_node"] == ["q-001", "q-002", "q-003", "q-004", "q-005"]
    assert payload["revision_feedback"]["rejected_question_ids"] == ["q-001"]
