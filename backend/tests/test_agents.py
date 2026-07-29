from app.agents import generator as generator_module
from app.agents.workflow import build_workflow, decide_next
from app.core.llm_gateway import LLMGateway
from app.models.llm import RawLLMResponse
from app.models.schemas import LearnerProfile
from tests.fakes.llm import ScriptedLLMTransport
from tests.fakes.evidence import make_evidence


def test_workflow_compiles_with_expected_baseline_channels():
    """工作流输入 schema 必须保留全部生成请求控制字段。"""
    workflow = build_workflow()
    schema = workflow.get_input_jsonschema()

    assert {
        "schema_version",
        "run_id",
        "learner_id",
        "learner",
        "topic",
        "knowledge_base_id",
        "diagnostic_result_id",
        "target_skill_nodes",
        "resource_types",
        "difficulty_preference",
        "generation_mode",
        "include_review",
        "include_claim_check",
        "max_iterations",
        "constraints",
        "trace",
        "errors",
    } <= set(schema["properties"])


def test_workflow_retry_guard_decides_after_max_iteration():
    assert decide_next({
        "review_result": {"decision": "revise"},
        "revision_count": 0,
        "max_iterations": 1,
    }) == "generate"
    assert decide_next({
        "review_result": {"decision": "revise"},
        "revision_count": 1,
        "max_iterations": 1,
    }) == "decide"


def test_generate_node_increments_iteration():
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
        "resources": [{
            "resource_type": "讲义",
            "difficulty": "初级",
            "content_text": "测试内容",
            "knowledge_points": ["测试"],
        }],
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
