from app.agents import generator as generator_module
from app.agents.workflow import build_workflow, decide_next
from app.models.schemas import LearnerProfile


class _FakeResponse:
    content = """[{"resource_type":"讲义","difficulty":"初级","content_text":"测试内容","knowledge_points":["测试"]}]"""


class _FakeLLM:
    def invoke(self, messages):
        return _FakeResponse()


def test_workflow_compiles_with_expected_baseline_channels():
    """只验证当前图可编译及基线 channel；完整离线 invoke 属于 P0-01。"""
    workflow = build_workflow()
    schema = workflow.get_input_jsonschema()

    assert {"learner", "topic", "knowledge_base_id", "trace", "iteration"} <= set(
        schema["properties"]
    )


def test_workflow_retry_guard_decides_after_max_iteration():
    assert decide_next({"review_result": {"passed": False}, "iteration": 0}) == "generate"
    assert decide_next({"review_result": {"passed": False}, "iteration": 2}) == "decide"


def test_generate_node_increments_iteration(monkeypatch):
    monkeypatch.setattr(generator_module, "get_llm", lambda: _FakeLLM())

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

    result = generator_module.generate_node({
        "learner": learner,
        "topic": "工业互联网",
        "resource_types": ["讲义"],
        "diagnosis": {},
        "retrieved_chunks": [],
        "learning_plan": {},
        "generated_resources": [],
        "review_result": {},
        "final_decision": "",
        "trace": [],
        "iteration": 0,
    })

    assert result["iteration"] == 1
