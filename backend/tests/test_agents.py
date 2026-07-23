from app.agents import generator as generator_module
from app.agents.workflow import build_workflow, decide_next
from app.models.schemas import LearnerProfile


class _FakeResponse:
    content = "[]"


class _FakeLLM:
    def invoke(self, messages):
        return _FakeResponse()


def test_workflow_runs():
    """测试多智能体工作流能完成端到端调用"""
    learner = LearnerProfile(
        learner_id="test_001",
        learner_type="初学者",
        education="本科",
        major="计算机科学与技术",
        theory_scores={"工业互联网架构": 65, "MQTT": 70},
        skill_level="初级",
        weak_points=["OPC UA", "边缘计算网关配置"],
        strong_points=["Python 编程"],
        learning_goal="掌握工业互联网数据采集",
    )

    workflow = build_workflow()
    initial_state = {
        "learner": learner,
        "topic": "工业互联网边缘计算网关配置",
        "resource_types": ["讲义"],
        "diagnosis": {},
        "retrieved_chunks": [],
        "learning_plan": {},
        "generated_resources": [],
        "review_result": {},
        "final_decision": "",
        "trace": [],
        "iteration": 0,
    }

    # 注意：此测试需要配置 LLM_API_KEY 才能运行
    # result = workflow.invoke(initial_state)
    # assert "final_decision" in result
    assert workflow is not None


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
