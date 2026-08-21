from app.agents import generator as generator_module
from app.core.llm_gateway import LLMGateway
from app.models.llm import RawLLMResponse
from app.models.schemas import LearnerProfile
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMTransport


def test_generate_node_preserves_legacy_iteration_projection():
    learner = LearnerProfile(
        learner_id="test_002",
        learner_type="初学者",
        education="本科",
        major="计算机科学与技术",
        theory_scores={},
        skill_level="初级",
        weak_points=[],
        strong_points=[],
        learning_goal="测试",
    )
    gateway = LLMGateway(ScriptedLLMTransport([RawLLMResponse(content={
        "difficulty": "初级",
        "title": "工业互联网测试讲义",
        "markdown_content": "# 工业互联网测试讲义\n\n## 学习目标\n\n测试内容",
        "knowledge_points": ["工业互联网"],
    })]))

    result = generator_module.generate_node({
        "learner": learner,
        "topic": "工业互联网",
        "resource_types": ["讲义"],
        "diagnosis": {},
        "retrieved_evidence": [make_evidence()],
        "learning_plan": {},
        "generated_resources": [],
        "review_result": {},
        "final_decision": "",
        "trace": [],
        "iteration": 0,
    }, llm_gateway=gateway)

    assert result["iteration"] == 1
    assert result["generation_attempt"] == 1
