from __future__ import annotations

import httpx
import pytest
from openai import InternalServerError, RateLimitError

from app.agents.diagnosis import diagnose_node
from app.agents.generator import GENERATION_PROMPT, generate_node
from app.agents.reviewer import review_node
from app.config import Settings
from app.core import errors as errors_module
from app.core.errors import ApplicationError, ErrorCode
from app.core.llm_gateway import LLMGateway
from app.models.llm import RawLLMResponse
from app.models.schemas import LearnerProfile
from tests.fakes.llm import ScriptedLLMGateway, ScriptedLLMTransport


def _settings(**overrides) -> Settings:
    values = {
        "_env_file": None,
        "app_mode": "demo",
        "allow_degraded_generation": True,
    }
    values.update(overrides)
    return Settings(**values)


def _learner() -> LearnerProfile:
    return LearnerProfile(
        learner_id="llm-policy",
        learner_type="初学者",
        education="本科",
        major="计算机",
        skill_level="初级",
        weak_points=["检索"],
        strong_points=["Python"],
        learning_goal="验证 LLM 失败策略",
    )


def _response_error(error_type, status):
    request = httpx.Request("POST", "https://provider.invalid/v1/chat")
    response = httpx.Response(status, request=request)
    return error_type("provider-secret", response=response, body={"secret": "hidden"})


def _review_state(**overrides):
    state = {
        "schema_version": "1.0",
        "run_id": "run-review-failure",
        "generation_mode": "standard",
        "generated_resources": [],
        "retrieved_chunks": [],
        "trace": [],
        "generation_attempt": 1,
        "revision_count": 0,
    }
    state.update(overrides)
    return state


@pytest.mark.parametrize(
    ("outcomes", "expected_code"),
    [
        ([TimeoutError("secret"), TimeoutError("secret")], ErrorCode.LLM_TIMEOUT),
        (
            [
                _response_error(RateLimitError, 429),
                _response_error(RateLimitError, 429),
            ],
            ErrorCode.LLM_RATE_LIMITED,
        ),
        (
            [
                _response_error(InternalServerError, 500),
                _response_error(InternalServerError, 503),
            ],
            ErrorCode.LLM_UPSTREAM_5XX,
        ),
        ([RawLLMResponse(content=""), RawLLMResponse(content="")], ErrorCode.LLM_OUTPUT_EMPTY),
        (
            [RawLLMResponse(content='{"decision"'), RawLLMResponse(content='{"decision"')],
            ErrorCode.LLM_OUTPUT_TRUNCATED,
        ),
        (
            [RawLLMResponse(content="not json"), RawLLMResponse(content="not json")],
            ErrorCode.LLM_OUTPUT_PARSE_FAILED,
        ),
        (
            [RawLLMResponse(content={"decision": "approve"})] * 2,
            ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
        ),
    ],
)
def test_reviewer_never_approves_gateway_failure(
    monkeypatch,
    outcomes,
    expected_code,
):
    monkeypatch.setattr(errors_module, "get_settings", lambda: _settings())
    gateway = LLMGateway(
        ScriptedLLMTransport(outcomes),
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    )

    result = review_node(_review_state(), llm_gateway=gateway)

    assert result["review_result"]["decision"] == "human_review"
    assert result["review_result"]["passed"] is False
    assert result["trace"][0]["status"] == "degraded"
    assert result["trace"][0]["error_code"] == expected_code.value
    assert "provider-secret" not in str(result)


def test_strict_mode_blocks_llm_fallback(monkeypatch):
    monkeypatch.setattr(errors_module, "get_settings", lambda: _settings())
    gateway = LLMGateway(
        ScriptedLLMTransport([TimeoutError("secret"), TimeoutError("secret")]),
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    )

    with pytest.raises(ApplicationError) as caught:
        review_node(
            _review_state(generation_mode="strict"),
            llm_gateway=gateway,
        )
    assert caught.value.code == ErrorCode.LLM_TIMEOUT


@pytest.mark.parametrize(
    ("requested", "expected"),
    [
        ("approve", "approve"),
        ("revise", "revise"),
        ("reject", "reject"),
    ],
)
def test_reviewer_accepts_only_typed_decisions(requested, expected):
    gateway = ScriptedLLMGateway([{
        "decision": requested,
        "hallucination_score": 0.0,
        "issues": [],
        "difficulty_match": True,
        "coverage_rate": 1.0,
        "suggestion": "已完成严格审核。",
        "revision_instructions": [],
    }])

    result = review_node(_review_state(), llm_gateway=gateway)

    assert result["review_result"]["decision"] == expected
    assert result["review_result"]["passed"] is (expected == "approve")


def test_diagnosis_trace_carries_sanitized_llm_telemetry_and_shared_ids():
    gateway = ScriptedLLMGateway([{
        "ability_tags": ["Python"],
        "weak_points": ["检索"],
        "recommended_difficulty": "初级",
        "suggestion": "先练习检索。",
    }])
    state = {
        "schema_version": "1.0",
        "run_id": "run-telemetry",
        "learner": _learner(),
        "topic": "向量检索",
        "generation_mode": "standard",
        "trace": [],
    }

    result = diagnose_node(state, llm_gateway=gateway)

    trace = result["trace"][0]
    call_context = gateway.calls[0]["context"]
    assert trace["run_id"] == call_context.run_id == "run-telemetry"
    assert trace["step_id"] == call_context.step_id
    assert trace["llm_call_id"] == call_context.call_id
    assert trace["model_name"] == "fake-model"
    assert trace["total_tokens"] == 15
    assert trace["llm_duration_ms"] == 2
    assert "messages" not in trace


def test_generator_builds_source_refs_only_from_retrieved_chunks():
    assert "source_refs" not in GENERATION_PROMPT
    gateway = ScriptedLLMGateway([{
        "resources": [{
            "resource_type": "讲义",
            "difficulty": "初级",
            "content_text": "系统绑定证据。",
            "knowledge_points": ["检索"],
        }],
    }])
    result = generate_node({
        "schema_version": "1.0",
        "run_id": "run-source-ref",
        "learner": _learner(),
        "topic": "检索",
        "resource_types": ["讲义"],
        "generation_mode": "standard",
        "retrieved_chunks": [{
            "document_id": "doc-system",
            "source": "system-source.md",
            "content": "可信知识片段",
            "score": 0.9,
        }],
        "trace": [],
    }, llm_gateway=gateway)

    source_ref = result["generated_resources"][0].source_refs[0]
    assert source_ref.doc_id == "doc-system"
    assert source_ref.title == "system-source.md"


def test_technical_retry_does_not_increment_business_revision_count():
    gateway = LLMGateway(
        ScriptedLLMTransport([
            TimeoutError("transient"),
            RawLLMResponse(
                content={
                    "resources": [{
                        "resource_type": "讲义",
                        "difficulty": "初级",
                        "content_text": "重试成功。",
                        "knowledge_points": ["检索"],
                    }],
                },
                finish_reason="stop",
            ),
        ]),
        sleep=lambda _: None,
        jitter=lambda: 0.0,
    )
    result = generate_node({
        "schema_version": "1.0",
        "run_id": "run-retry-count",
        "learner": _learner(),
        "topic": "检索",
        "resource_types": ["讲义"],
        "generation_mode": "standard",
        "retrieved_chunks": [],
        "generation_attempt": 2,
        "revision_count": 1,
        "trace": [],
    }, llm_gateway=gateway)

    assert result["generation_attempt"] == 2
    assert result["iteration"] == 2
    assert "revision_count" not in result
    assert result["trace"][0]["retry_count"] == 1
    assert result["trace"][0]["attempt"] == 2
    assert result["trace"][0]["finish_reason"] == "stop"
