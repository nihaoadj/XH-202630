from datetime import datetime, timedelta, timezone

import httpx
import pytest
from langchain_core.messages import HumanMessage
from openai import (
    APIConnectionError,
    AuthenticationError,
    BadRequestError,
    InternalServerError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict

from app.core.security.errors import ErrorCode
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import (
    LLMCallContext,
    LLMCallOptions,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from tests.fakes.llm import ScriptedLLMTransport


class Payload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    value: str


def raw(
    content,
    *,
    usage=None,
    finish_reason="stop",
    mode=StructuredOutputMode.TEXT,
):
    return RawLLMResponse(
        content=content,
        usage=usage or LLMUsage(),
        finish_reason=finish_reason,
        provider_request_id="provider-request",
        structured_output_mode=mode,
    )


def context(**overrides):
    values = {
        "run_id": "run-1",
        "step_id": "step-1",
        "node_name": "diagnosis",
        "schema_name": "Payload",
    }
    values.update(overrides)
    return LLMCallContext(**values)


def options(**overrides):
    values = {
        "structured_output_mode": StructuredOutputMode.TEXT,
        "max_attempts": 2,
        "request_timeout_seconds": 10,
    }
    values.update(overrides)
    return LLMCallOptions(**values)


def response_error(error_type, status, *, headers=None):
    request = httpx.Request("POST", "https://provider.invalid/v1/chat")
    response = httpx.Response(status, request=request, headers=headers)
    return error_type("provider-secret-message", response=response, body={"secret": "hidden"})


def test_gateway_success_returns_typed_output_and_telemetry():
    transport = ScriptedLLMTransport([
        raw(
            '{"value":"ok"}',
            usage=LLMUsage(input_tokens=3, output_tokens=2, total_tokens=5),
        )
    ])
    gateway = LLMGateway(transport)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(max_attempts=1),
    )

    assert result.output == Payload(value="ok")
    assert result.attempt_count == 1
    assert result.retry_count == 0
    assert result.usage.total_tokens == 5
    assert result.provider_request_id == "provider-request"
    assert result.call_id


def test_gateway_retries_timeout_without_changing_call_identity():
    sleeps = []
    transport = ScriptedLLMTransport([TimeoutError("secret"), raw('{"value":"ok"}')])
    gateway = LLMGateway(transport, sleep=sleeps.append, jitter=lambda: 0.0)
    call_context = context()

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=call_context,
        options=options(),
    )

    assert result.call_id == call_context.call_id
    assert result.attempt_count == 2
    assert result.retry_count == 1
    assert result.attempts[0].error_code == ErrorCode.LLM_TIMEOUT.value
    assert sleeps == [0.5]


def test_gateway_honors_bounded_retry_after():
    sleeps = []
    limited = response_error(RateLimitError, 429, headers={"Retry-After": "30"})
    transport = ScriptedLLMTransport([limited, raw('{"value":"ok"}')])
    gateway = LLMGateway(
        transport,
        retry_max_delay_seconds=3.0,
        sleep=sleeps.append,
        jitter=lambda: 0.0,
    )

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(),
    )

    assert result.retry_count == 1
    assert result.attempts[0].error_code == ErrorCode.LLM_RATE_LIMITED.value
    assert sleeps == [3.0]


def test_gateway_retries_connection_error_once():
    request = httpx.Request("POST", "https://provider.invalid/v1/chat")
    transport = ScriptedLLMTransport([
        APIConnectionError(request=request),
        raw('{"value":"ok"}'),
    ])
    gateway = LLMGateway(transport, sleep=lambda _: None, jitter=lambda: 0.0)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(),
    )

    assert result.retry_count == 1
    assert result.attempts[0].error_code == ErrorCode.LLM_CONNECTION_FAILED.value


def test_gateway_retries_unclassified_provider_adapter_failure():
    """Compatibility-layer errors must use the bounded upstream retry budget."""

    transport = ScriptedLLMTransport([
        RuntimeError("adapter implementation detail must not leak"),
        raw('{"value":"ok"}'),
    ])
    gateway = LLMGateway(transport, sleep=lambda _: None, jitter=lambda: 0.0)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(node_name="text_resource_agent"),
        options=options(),
    )

    assert result.output == Payload(value="ok")
    assert result.retry_count == 1
    assert result.attempts[0].error_code == ErrorCode.LLM_UPSTREAM_UNAVAILABLE.value


def test_gateway_classifies_length_finish_reason_as_truncated_and_retries():
    length_failure = type("LengthFinishReasonError", (Exception,), {})()
    transport = ScriptedLLMTransport([length_failure, raw('{"value":"ok"}')])
    gateway = LLMGateway(transport, sleep=lambda _: None, jitter=lambda: 0.0)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(node_name="text_resource_agent"),
        options=options(),
    )

    assert result.output == Payload(value="ok")
    assert result.attempts[0].error_code == ErrorCode.LLM_OUTPUT_TRUNCATED.value


def test_gateway_does_not_retry_bad_request_and_sanitizes_error():
    bad_request = response_error(BadRequestError, 400)
    transport = ScriptedLLMTransport([bad_request, raw('{"value":"unused"}')])
    gateway = LLMGateway(transport)

    with pytest.raises(LLMGatewayError) as caught:
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(),
            options=options(),
        )

    assert caught.value.error.code == ErrorCode.LLM_BAD_REQUEST.value
    assert caught.value.retry_count == 0
    assert len(transport.calls) == 1
    assert "provider-secret-message" not in str(caught.value)


def test_gateway_does_not_retry_auth_error():
    auth_error = response_error(AuthenticationError, 401)
    transport = ScriptedLLMTransport([auth_error, raw('{"value":"unused"}')])
    gateway = LLMGateway(transport)

    with pytest.raises(LLMGatewayError) as caught:
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(),
            options=options(),
        )

    assert caught.value.error.code == ErrorCode.LLM_AUTH_FAILED.value
    assert len(transport.calls) == 1


def test_gateway_stops_after_max_attempts_for_5xx():
    first = response_error(InternalServerError, 500)
    second = response_error(InternalServerError, 503)
    transport = ScriptedLLMTransport([first, second])
    gateway = LLMGateway(transport, sleep=lambda _: None, jitter=lambda: 0.0)

    with pytest.raises(LLMGatewayError) as caught:
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(),
            options=options(),
        )

    assert caught.value.error.code == ErrorCode.LLM_UPSTREAM_5XX.value
    assert caught.value.retry_count == 1
    assert len(transport.calls) == 2


def test_gateway_schema_repair_uses_same_global_attempt_budget():
    transport = ScriptedLLMTransport([
        raw('{"wrong":"field"}'),
        raw('{"value":"repaired"}'),
    ])
    gateway = LLMGateway(transport)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(),
    )

    assert result.output.value == "repaired"
    assert result.retry_count == 1
    assert result.attempts[0].error_code == ErrorCode.LLM_OUTPUT_SCHEMA_INVALID.value
    assert len(transport.calls) == 2
    assert len(transport.calls[1]["messages"]) > len(transport.calls[0]["messages"])


def test_gateway_recovers_empty_output_with_fresh_prompt_and_bounded_retry():
    sleeps = []
    transport = ScriptedLLMTransport([
        raw(""),
        raw(""),
        raw('{"value":"recovered"}'),
    ])
    gateway = LLMGateway(transport, sleep=sleeps.append, jitter=lambda: 0.0)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(max_attempts=3),
    )

    assert result.output == Payload(value="recovered")
    assert result.attempt_count == 3
    assert result.retry_count == 2
    assert [item.error_code for item in result.attempts[:2]] == [
        ErrorCode.LLM_OUTPUT_EMPTY.value,
        ErrorCode.LLM_OUTPUT_EMPTY.value,
    ]
    assert sleeps == [0.5, 1.0]
    assert any(
        "没有返回任何有效内容" in str(message.content)
        for message in transport.calls[1]["messages"]
    )
    assert "" not in [
        message.content
        for message in transport.calls[1]["messages"]
        if getattr(message, "type", "") == "ai"
    ]


def test_resource_agents_receive_dedicated_empty_output_recovery_budget():
    gateway = LLMGateway(
        ScriptedLLMTransport([]),
        default_options=options(max_attempts=2),
        resource_generation_max_attempts=3,
    )

    assert gateway.options_for("text_resource_agent").max_attempts == 3
    assert gateway.options_for("assessment_agent").max_attempts == 3
    assert gateway.options_for("reviewer").max_attempts == 2


@pytest.mark.parametrize(
    "first",
    [
        raw("not json"),
        raw('{"value"', finish_reason="length"),
    ],
)
def test_gateway_repairs_parse_and_truncated_output(first):
    transport = ScriptedLLMTransport([first, raw('{"value":"repaired"}')])
    gateway = LLMGateway(transport)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(),
    )

    assert result.output.value == "repaired"
    assert result.attempt_count == 2


def test_gateway_stops_when_repair_budget_is_exhausted():
    transport = ScriptedLLMTransport([
        raw("bad"),
        raw("still bad"),
        raw('{"value":"must-not-be-used"}'),
    ])
    gateway = LLMGateway(transport)

    with pytest.raises(LLMGatewayError) as caught:
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(),
            options=options(max_attempts=3),
        )

    assert caught.value.error.code == ErrorCode.LLM_OUTPUT_PARSE_FAILED.value
    assert caught.value.retry_count == 1
    assert len(transport.calls) == 2


def test_gateway_jitter_never_exceeds_max_delay():
    transport = ScriptedLLMTransport([TimeoutError("one"), raw('{"value":"ok"}')])
    sleeps = []
    gateway = LLMGateway(
        transport,
        retry_base_delay_seconds=3.0,
        retry_max_delay_seconds=3.0,
        sleep=sleeps.append,
        jitter=lambda: 1.0,
    )

    gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(),
    )

    assert sleeps == [3.0]


def test_auto_mode_falls_back_to_text_once_for_structured_bad_request():
    bad_request = response_error(BadRequestError, 400)
    transport = ScriptedLLMTransport([bad_request, raw('{"value":"text"}')])
    gateway = LLMGateway(transport)

    result = gateway.invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(structured_output_mode=StructuredOutputMode.AUTO),
    )

    assert result.output.value == "text"
    assert [call["mode"] for call in transport.calls] == [
        StructuredOutputMode.FUNCTION_CALLING,
        StructuredOutputMode.TEXT,
    ]


def test_explicit_text_mode_never_probes_function_calling():
    transport = ScriptedLLMTransport([raw('{"value":"text"}')])
    result = LLMGateway(transport).invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(structured_output_mode=StructuredOutputMode.TEXT),
    )

    assert result.output.value == "text"
    assert result.attempt_count == 1
    assert [call["mode"] for call in transport.calls] == [StructuredOutputMode.TEXT]


def test_json_mode_adds_provider_required_schema_on_first_attempt():
    transport = ScriptedLLMTransport([raw({"value": "json"})])

    result = LLMGateway(transport).invoke_structured(
        messages=[HumanMessage(content="test")],
        output_schema=Payload,
        context=context(),
        options=options(structured_output_mode=StructuredOutputMode.JSON_MODE),
    )

    assert result.output.value == "json"
    assert [call["mode"] for call in transport.calls] == [StructuredOutputMode.JSON_MODE]
    instruction = transport.calls[0]["messages"][0].content
    assert "valid json object" in instruction
    assert '"value"' in instruction
    assert '"required"' in instruction


def test_explicit_structured_mode_does_not_fall_back_to_text():
    bad_request = response_error(BadRequestError, 400)
    transport = ScriptedLLMTransport([bad_request, raw('{"value":"unused"}')])
    gateway = LLMGateway(transport)

    with pytest.raises(LLMGatewayError):
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(),
            options=options(
                structured_output_mode=StructuredOutputMode.FUNCTION_CALLING
            ),
        )

    assert len(transport.calls) == 1


def test_expired_workflow_deadline_makes_no_transport_call():
    transport = ScriptedLLMTransport([raw('{"value":"unused"}')])
    gateway = LLMGateway(transport)

    with pytest.raises(LLMGatewayError) as caught:
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(
                workflow_deadline_at=datetime.now(timezone.utc) - timedelta(seconds=1)
            ),
            options=options(),
        )

    assert caught.value.error.code == ErrorCode.LLM_TIMEOUT.value
    assert transport.calls == []


def test_retry_does_not_sleep_past_remaining_deadline():
    transport = ScriptedLLMTransport([TimeoutError("secret"), raw('{"value":"unused"}')])
    sleeps = []
    now = datetime(2026, 7, 29, tzinfo=timezone.utc)
    gateway = LLMGateway(
        transport,
        sleep=sleeps.append,
        wall_clock=lambda: now,
        jitter=lambda: 0.0,
    )

    with pytest.raises(LLMGatewayError):
        gateway.invoke_structured(
            messages=[HumanMessage(content="test")],
            output_schema=Payload,
            context=context(workflow_deadline_at=now + timedelta(seconds=0.1)),
            options=options(),
        )

    assert len(transport.calls) == 1
    assert sleeps == []


def test_plain_text_generation_does_not_send_a_json_schema_or_parse_json():
    transport = ScriptedLLMTransport([
        raw("# 讲义\n\n## 学习目标\n\n直接输出 Markdown。"),
    ])

    result = LLMGateway(transport).invoke_plain_text(
        messages=[HumanMessage(content="write markdown")],
        context=context(node_name="TextResourceAgent", schema_name="plain_markdown"),
        options=options(max_attempts=1, max_output_tokens=10240),
    )

    assert result.output.startswith("# 讲义")
    assert result.structured_output_mode == StructuredOutputMode.TEXT
    assert transport.calls[0]["mode"] == StructuredOutputMode.TEXT
    assert transport.calls[0]["messages"][0].content == "write markdown"


def test_plain_text_retries_a_length_stop_with_compact_markdown_instruction():
    sleeps = []
    transport = ScriptedLLMTransport([
        raw("# 未完成", finish_reason="length"),
        raw("# 完整讲义\n\n## 总结\n\n完成。"),
    ])
    result = LLMGateway(transport, sleep=sleeps.append, jitter=lambda: 0.0).invoke_plain_text(
        messages=[HumanMessage(content="write markdown")],
        context=context(node_name="TextResourceAgent", schema_name="plain_markdown"),
        options=options(),
    )

    assert result.retry_count == 1
    assert result.output.startswith("# 完整讲义")
    assert transport.calls[1]["messages"][0].content.startswith("上一轮 Markdown")
