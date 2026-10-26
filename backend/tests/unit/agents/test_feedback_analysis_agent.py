"""Feedback explanations retain frozen facts and the existing fallback boundary."""
import json
from types import SimpleNamespace

import pytest

from app.agents.learning_agents.feedback_analysis_agent import analyze_feedback
from app.core.llm.gateway import LLMGatewayError
from app.core.security.errors import ErrorCode
from app.db.feedback.memory import MemoryFeedbackRepository
from app.models.feedback.feedback_loop import FeedbackAnalysis
from app.models.shared.common import ErrorInfo
from app.services.feedback.feedback import FeedbackService


def _inputs():
    return (
        SimpleNamespace(skill_level="初级", weak_points=["node"]),
        SimpleNamespace(metadata={"total_score": 7, "max_score": 10, "learning_reflection": {"comment": "合成感受"}},
                        overall_score=0.7, source_run_id=None, learner_id="learner", idempotency_key="fixture",
                        knowledge_point_results=[SimpleNamespace(knowledge_point_id="node", score=0.7, correct_count=0, total_count=1)]),
        SimpleNamespace(action=SimpleNamespace(value="reinforce"), decision_reason="合成原因"),
        [SimpleNamespace(knowledge_point_id="node", after=SimpleNamespace(status="weak", mastery=0.7))],
    )


class _Gateway:
    def __init__(self, failure=None, empty=False):
        self.failure, self.empty = failure, empty
        self.calls = []

    def options_for(self, node, **kwargs):
        assert (node, kwargs) == ("feedback_analysis", {"temperature": 0.2})
        return {"temperature": 0.2}

    def invoke_structured(self, **kwargs):
        self.calls.append(kwargs)
        if self.failure:
            raise self.failure
        return SimpleNamespace(output=None if self.empty else FeedbackAnalysis(
            summary="合成小结", reflection_insight="合成观察", learner_suggestions=["合成建议"], analysis_status="fallback",
        ))


def test_analysis_agent_preserves_facts_compact_json_and_context():
    gateway = _Gateway()
    analyze_feedback(gateway, *_inputs())
    call, = gateway.calls
    assert call["output_schema"] is FeedbackAnalysis
    context = call["context"]
    assert (context.run_id, context.step_id, context.node_name, context.schema_name, context.generation_attempt) == (
        "feedback:learner", "feedback-analysis:fixture", "feedback_analysis_agent", "FeedbackAnalysis", 1,
    )
    human = call["messages"][1].content
    payload = json.loads(human)
    assert human == json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    assert payload["objective_scores"]["score_rate"] == 0.7
    assert payload["objective_scores"]["knowledge_points"][0]["correct_count"] == 0
    assert payload["objective_scores"]["knowledge_points"][0]["score_is_weighted"] is True
    assert payload["learner_reflection"] == {"comment": "合成感受"}
    assert payload["mastery_updates"] == [{"knowledge_point_id": "node", "status": "weak", "mastery": 0.7}]
    assert "不得改写分数" in call["messages"][0].content


def test_service_retains_llm_status_and_empty_result_fallback():
    profile, request, policy, mutations = _inputs()
    service = FeedbackService(MemoryFeedbackRepository(), llm_gateway=_Gateway())
    assert service._analyze_feedback(profile, request, policy, mutations).analysis_status == "llm"
    for gateway in (None, _Gateway(empty=True)):
        service.llm_gateway = gateway
        result = service._analyze_feedback(profile, request, policy, mutations)
        assert (result.analysis_status, result.summary) == ("fallback", "合成原因")
        assert result.profile_update_suggestions == ["关注：node"]


def test_service_catches_gateway_failure_but_preserves_other_errors():
    gateway_error = LLMGatewayError(error=ErrorInfo(code=ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
                                                  category="synthetic", message="synthetic", source="fixture"),
                                    call_id="synthetic", retry_count=0, latency_ms=0, attempts=[])
    service = FeedbackService(MemoryFeedbackRepository(), llm_gateway=_Gateway(failure=gateway_error))
    assert service._analyze_feedback(*_inputs()).analysis_status == "fallback"
    service.llm_gateway = _Gateway(failure=ValueError("synthetic"))
    with pytest.raises(ValueError, match="synthetic"):
        service._analyze_feedback(*_inputs())
