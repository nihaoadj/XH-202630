"""Freeze grading's model boundary while the service retains scoring policy."""
import json
from types import SimpleNamespace

import pytest

from app.agents.learning_agents.short_answer_grader_agent import grade_short_answer
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.feedback.memory import MemoryFeedbackRepository
from app.models.shared.agent_contracts import AssessmentShortAnswerGradeV1
from app.services.feedback.feedback import FeedbackService


class _Gateway:
    def __init__(self, score=6.65, failure=None):
        self.score = score
        self.failure = failure
        self.calls = []
        self.options = object()

    def options_for(self, node, **kwargs):
        assert (node, kwargs) == ("feedback_agent", {"temperature": 0.0})
        return self.options

    def invoke_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(output=kwargs["output_schema"](score=self.score, feedback="合成评分依据"))


def _question(maximum=10):
    return {"question_id": "q-synthetic", "stem": "合成题干", "reference_answer": "冻结答案",
            "rubric": [{"criterion": "引用依据", "points": maximum}], "max_score": maximum}


def test_agent_keeps_schema_context_temperature_and_empty_answer_payload():
    gateway = _Gateway()
    grade_short_answer(gateway, _question(), None, maximum=10.0)
    call, = gateway.calls
    assert call["output_schema"] is AssessmentShortAnswerGradeV1
    assert call["options"] is gateway.options
    assert call["context"].model_dump(exclude={"call_id"}) == {
        "run_id": "feedback-grading", "step_id": "q-synthetic", "node_name": "short_answer_grader",
        "schema_name": "AssessmentShortAnswerGradeV1", "generation_attempt": 1, "workflow_deadline_at": None,
    }
    assert [message.type for message in call["messages"]] == ["system", "human"]
    assert call["messages"][0].content == (
        "你是分阶测试反馈评分 Agent。按参考答案和 rubric 逐项评分，只返回结构化得分和简短反馈。"
        "分数必须在 0 到 max_score 之间；空答案必须得 0 分；不要因表达方式不同而重复扣分。"
    )
    prompt = json.loads(call["messages"][1].content)
    assert prompt["learner_answer"] == ""
    assert (prompt["question"], prompt["reference_answer"], prompt["max_score"]) == ("合成题干", "冻结答案", 10.0)
    assert prompt["rubric"] == _question()["rubric"]
    assert len(prompt["scoring_rules"]) == 3


@pytest.mark.parametrize("score,maximum,expected", [(6.65, 10, 0.67), (10, 5, 1.0), (0, 10, 0.0)])
def test_service_retains_half_up_rounding_and_upper_clamp(score, maximum, expected):
    service = FeedbackService(MemoryFeedbackRepository(), llm_gateway=_Gateway(score))
    assert service._short_answer_score(_question(maximum), "合成作答") == expected


@pytest.mark.parametrize("gateway,maximum,code,status", [
    (None, 10, ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, 503),
    (_Gateway(), 0, ErrorCode.FEEDBACK_ATTEMPT_INVALID, 422),
    (_Gateway(failure=TimeoutError("synthetic")), 10, ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, 503),
    (_Gateway(score=16), 10, ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, 503),
])
def test_service_retains_error_mapping(gateway, maximum, code, status):
    service = FeedbackService(MemoryFeedbackRepository(), llm_gateway=gateway)
    with pytest.raises(ApplicationError) as error:
        service._short_answer_score(_question(maximum), "合成作答")
    assert (error.value.code, error.value.status_code) == (code, status)
