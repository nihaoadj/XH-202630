from collections.abc import Callable
from typing import Any

from app.core.llm.structured_output import parse_structured_output
from app.models.shared.llm import (
    LLMAttemptSummary,
    LLMCallOptions,
    LLMCallResult,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)


class ScriptedLLMTransport:
    def __init__(self, outcomes: list[Any], model_name: str = "fake-model"):
        self.outcomes = list(outcomes)
        self.model_name = model_name
        self.calls: list[dict[str, Any]] = []

    def invoke(self, **kwargs) -> RawLLMResponse:
        self.calls.append(kwargs)
        if not self.outcomes:
            raise AssertionError("No scripted LLM outcome remains")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Callable):
            outcome = outcome(kwargs)
        return outcome


class ScriptedLLMGateway:
    """Offline injected fake for Agent/workflow contract tests."""

    def __init__(self, outcomes: list[Any], model_name: str = "fake-model"):
        self.outcomes = list(outcomes)
        self.model_name = model_name
        self.calls: list[dict[str, Any]] = []

    def options_for(self, node_name: str, *, temperature: float = 0.0) -> LLMCallOptions:
        return LLMCallOptions(
            max_attempts=1,
            temperature=temperature,
            structured_output_mode=StructuredOutputMode.TEXT,
        )

    def invoke_structured(self, **kwargs) -> LLMCallResult:
        self.calls.append(kwargs)
        if not self.outcomes:
            raise AssertionError("No scripted Gateway outcome remains")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Callable):
            outcome = outcome(kwargs)
        if isinstance(outcome, LLMCallResult):
            return outcome

        context = kwargs["context"]
        output = parse_structured_output(outcome, kwargs["output_schema"])
        usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        attempt = LLMAttemptSummary(
            attempt=1,
            status="success",
            latency_ms=2,
            structured_output_mode=StructuredOutputMode.TEXT,
            usage=usage,
        )
        return LLMCallResult(
            output=output,
            call_id=context.call_id,
            model_name=self.model_name,
            provider_request_id="fake-request",
            structured_output_mode=StructuredOutputMode.TEXT,
            attempt_count=1,
            retry_count=0,
            latency_ms=2,
            finish_reason="stop",
            usage=usage,
            attempts=[attempt],
        )

    def invoke_plain_text(self, **kwargs) -> LLMCallResult:
        self.calls.append(kwargs)
        if not self.outcomes:
            raise AssertionError("No scripted Gateway outcome remains")
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        if isinstance(outcome, Callable):
            outcome = outcome(kwargs)
        if isinstance(outcome, LLMCallResult):
            return outcome
        context = kwargs["context"]
        usage = LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15)
        return LLMCallResult(
            output=str(outcome), call_id=context.call_id, model_name=self.model_name,
            provider_request_id="fake-request", structured_output_mode=StructuredOutputMode.TEXT,
            attempt_count=1, retry_count=0, latency_ms=2, finish_reason="stop", usage=usage,
            attempts=[LLMAttemptSummary(attempt=1, status="success", latency_ms=2,
                                        structured_output_mode=StructuredOutputMode.TEXT, usage=usage)],
        )
