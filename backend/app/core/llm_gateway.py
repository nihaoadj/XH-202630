"""Bounded, observable and provider-neutral LLM invocation gateway."""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, Callable, Protocol, TypeVar

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    UnprocessableEntityError,
)
from pydantic import BaseModel

from app.config import get_settings
from app.core.errors import ErrorCode, PUBLIC_MESSAGES
from app.core.llm import LangChainChatTransport
from app.core.structured_output import StructuredOutputError, parse_structured_output
from app.models.llm import (
    LLMAttemptSummary,
    LLMCallContext,
    LLMCallOptions,
    LLMCallResult,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from app.models.workflow import ErrorInfo


logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class LLMTransport(Protocol):
    model_name: str

    def invoke(
        self,
        *,
        messages: list[BaseMessage],
        output_schema: type,
        mode: StructuredOutputMode,
        timeout_seconds: float,
        temperature: float,
        max_output_tokens: int,
    ) -> RawLLMResponse: ...


class LLMGatewayError(Exception):
    """Sanitized final failure from one bounded LLM call."""

    def __init__(
        self,
        *,
        error: ErrorInfo,
        call_id: str,
        retry_count: int,
        latency_ms: int,
        attempts: list[LLMAttemptSummary],
        finish_reason: str | None = None,
        model_name: str | None = None,
        structured_output_mode: StructuredOutputMode | None = None,
        usage: LLMUsage | None = None,
    ):
        self.error = error
        self.call_id = call_id
        self.retry_count = retry_count
        self.latency_ms = latency_ms
        self.attempts = attempts
        self.finish_reason = finish_reason
        self.model_name = model_name
        self.structured_output_mode = structured_output_mode
        self.usage = usage or LLMUsage()
        super().__init__(error.code)

    def trace_metadata(self) -> dict[str, Any]:
        return {
            "llm_call_id": self.call_id,
            "model_name": self.model_name,
            "structured_output_mode": (
                self.structured_output_mode.value
                if self.structured_output_mode is not None
                else None
            ),
            "finish_reason": self.finish_reason,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
            "llm_duration_ms": self.latency_ms,
            "retry_count": self.retry_count,
        }


class _MappedFailure(Exception):
    def __init__(
        self,
        code: ErrorCode,
        *,
        retryable: bool,
        category: str,
        safe_detail: str | None = None,
        retry_after: float | None = None,
    ):
        self.code = code
        self.retryable = retryable
        self.category = category
        self.safe_detail = safe_detail
        self.retry_after = retry_after
        super().__init__(code.value)


def _numeric_retry_after(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if not headers:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return None


def _map_exception(exc: Exception) -> _MappedFailure:
    if isinstance(exc, (APITimeoutError, TimeoutError)):
        return _MappedFailure(ErrorCode.LLM_TIMEOUT, retryable=True, category="timeout")
    if isinstance(exc, RateLimitError):
        return _MappedFailure(
            ErrorCode.LLM_RATE_LIMITED,
            retryable=True,
            category="rate_limit",
            retry_after=_numeric_retry_after(exc),
        )
    if isinstance(exc, APIConnectionError):
        return _MappedFailure(
            ErrorCode.LLM_CONNECTION_FAILED,
            retryable=True,
            category="transport",
        )
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        return _MappedFailure(ErrorCode.LLM_AUTH_FAILED, retryable=False, category="auth")
    if isinstance(exc, (BadRequestError, NotFoundError, UnprocessableEntityError)):
        return _MappedFailure(ErrorCode.LLM_BAD_REQUEST, retryable=False, category="request")
    if isinstance(exc, APIStatusError):
        if exc.status_code >= 500:
            return _MappedFailure(
                ErrorCode.LLM_UPSTREAM_5XX,
                retryable=True,
                category="upstream",
            )
        return _MappedFailure(ErrorCode.LLM_BAD_REQUEST, retryable=False, category="request")
    return _MappedFailure(
        ErrorCode.LLM_UPSTREAM_UNAVAILABLE,
        retryable=False,
        category="upstream",
    )


def _error_info(failure: _MappedFailure, *, source: str, attempt: int) -> ErrorInfo:
    return ErrorInfo(
        code=failure.code.value,
        category=failure.category,
        message=PUBLIC_MESSAGES.get(failure.code, "大模型服务当前不可用"),
        retryable=failure.retryable,
        source=source,
        attempt=attempt,
        safe_detail=failure.safe_detail,
    )


def _usage_complete(usages: list[LLMUsage]) -> LLMUsage:
    if not usages:
        return LLMUsage()

    def total(field: str) -> int | None:
        values = [getattr(usage, field) for usage in usages]
        if any(value is None for value in values):
            return None
        return sum(values)  # type: ignore[arg-type]

    return LLMUsage(
        input_tokens=total("input_tokens"),
        output_tokens=total("output_tokens"),
        total_tokens=total("total_tokens"),
    )


def _serialize_repair_value(value: Any) -> str:
    if isinstance(value, BaseModel):
        text = value.model_dump_json()
    elif isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False)
    else:
        text = str(value)
    return text[:12000]


class LLMGateway:
    def __init__(
        self,
        transport: LLMTransport,
        *,
        retry_base_delay_seconds: float = 0.5,
        retry_max_delay_seconds: float = 3.0,
        default_options: LLMCallOptions | None = None,
        generator_max_output_tokens: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        jitter: Callable[[], float] = random.random,
    ):
        self.transport = transport
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.default_options = default_options or LLMCallOptions()
        self.generator_max_output_tokens = (
            generator_max_output_tokens or self.default_options.max_output_tokens
        )
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.jitter = jitter

    def options_for(
        self,
        node_name: str,
        *,
        temperature: float = 0.0,
    ) -> LLMCallOptions:
        """Return one immutable-per-call copy of the configured retry budget."""

        max_tokens = (
            self.generator_max_output_tokens
            if node_name == "generator"
            else self.default_options.max_output_tokens
        )
        return self.default_options.model_copy(update={
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        })

    def _remaining_seconds(self, context: LLMCallContext) -> float | None:
        if context.workflow_deadline_at is None:
            return None
        deadline = context.workflow_deadline_at
        if deadline.tzinfo is None:
            deadline = deadline.replace(tzinfo=timezone.utc)
        return (deadline - self.wall_clock()).total_seconds()

    def _delay_for(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return min(retry_after, self.retry_max_delay_seconds)
        exponential = self.retry_base_delay_seconds * (2 ** max(0, attempt - 1))
        bounded = min(exponential, self.retry_max_delay_seconds)
        jittered = bounded + min(self.retry_base_delay_seconds, bounded) * self.jitter()
        return min(jittered, self.retry_max_delay_seconds)

    @staticmethod
    def _text_messages(
        messages: list[BaseMessage],
        output_schema: type[BaseModel],
    ) -> list[BaseMessage]:
        schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "仅返回一个符合以下 JSON Schema 的 JSON 对象，不要添加 Markdown 或解释：\n"
            f"{schema}"
        )
        return [SystemMessage(content=instruction), *messages]

    @staticmethod
    def _repair_messages(
        messages: list[BaseMessage],
        output_schema: type[BaseModel],
        raw_value: Any,
        failure: _MappedFailure,
    ) -> list[BaseMessage]:
        schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        repair = (
            "上一次输出未通过结构校验。请仅返回修复后的 JSON 对象，不要解释。\n"
            f"错误：{failure.code.value}:{failure.safe_detail or 'invalid_output'}\n"
            f"JSON Schema：{schema}"
        )
        return [
            *messages,
            AIMessage(content=_serialize_repair_value(raw_value)),
            SystemMessage(content=repair),
        ]

    def _raise_final(
        self,
        *,
        failure: _MappedFailure,
        context: LLMCallContext,
        attempt: int,
        started_at: float,
        attempts: list[LLMAttemptSummary],
        finish_reason: str | None,
    ) -> None:
        latency_ms = max(0, int((self.monotonic() - started_at) * 1000))
        retry_count = max(0, len(attempts) - 1)
        error = _error_info(failure, source=context.node_name, attempt=attempt)
        logger.warning(
            "LLM call failed run_id=%s step_id=%s call_id=%s node=%s code=%s attempt=%s retry_count=%s",
            context.run_id,
            context.step_id,
            context.call_id,
            context.node_name,
            failure.code.value,
            attempt,
            retry_count,
        )
        raise LLMGatewayError(
            error=error,
            call_id=context.call_id,
            retry_count=retry_count,
            latency_ms=latency_ms,
            attempts=attempts,
            finish_reason=finish_reason,
            model_name=self.transport.model_name,
            structured_output_mode=(
                attempts[-1].structured_output_mode if attempts else None
            ),
            usage=_usage_complete([item.usage for item in attempts]),
        )

    def invoke_structured(
        self,
        *,
        messages: list[BaseMessage],
        output_schema: type[T],
        context: LLMCallContext,
        options: LLMCallOptions,
    ) -> LLMCallResult[T]:
        started_at = self.monotonic()
        attempts: list[LLMAttemptSummary] = []
        usages: list[LLMUsage] = []
        auto_mode = options.structured_output_mode == StructuredOutputMode.AUTO
        mode = (
            StructuredOutputMode.FUNCTION_CALLING
            if auto_mode
            else options.structured_output_mode
        )
        call_messages = list(messages)
        finish_reason: str | None = None
        repair_used = False

        for attempt in range(1, options.max_attempts + 1):
            remaining = self._remaining_seconds(context)
            if remaining is not None and remaining <= 0:
                failure = _MappedFailure(
                    ErrorCode.LLM_TIMEOUT,
                    retryable=True,
                    category="timeout",
                    safe_detail="workflow_deadline_exhausted",
                )
                self._raise_final(
                    failure=failure,
                    context=context,
                    attempt=max(1, attempt),
                    started_at=started_at,
                    attempts=attempts,
                    finish_reason=finish_reason,
                )

            timeout = options.request_timeout_seconds
            if remaining is not None:
                timeout = min(timeout, max(0.001, remaining))
            prepared_messages = (
                self._text_messages(call_messages, output_schema)
                if mode == StructuredOutputMode.TEXT
                else call_messages
            )
            attempt_started = self.monotonic()
            raw: RawLLMResponse | None = None
            try:
                raw = self.transport.invoke(
                    messages=prepared_messages,
                    output_schema=output_schema,
                    mode=mode,
                    timeout_seconds=timeout,
                    temperature=options.temperature,
                    max_output_tokens=options.max_output_tokens,
                )
                finish_reason = raw.finish_reason
                if raw.response_metadata.get("refusal") or finish_reason == "content_filter":
                    raise _MappedFailure(
                        ErrorCode.LLM_CONTENT_REFUSED,
                        retryable=False,
                        category="content",
                    )
                output = parse_structured_output(
                    raw.content,
                    output_schema,
                    finish_reason=finish_reason,
                )
                attempt_latency = max(
                    0,
                    int((self.monotonic() - attempt_started) * 1000),
                )
                usages.append(raw.usage)
                attempts.append(LLMAttemptSummary(
                    attempt=attempt,
                    status="success",
                    latency_ms=attempt_latency,
                    structured_output_mode=mode,
                    usage=raw.usage,
                ))
                return LLMCallResult[T](
                    output=output,
                    call_id=context.call_id,
                    model_name=self.transport.model_name,
                    provider_request_id=raw.provider_request_id,
                    structured_output_mode=mode,
                    attempt_count=attempt,
                    retry_count=attempt - 1,
                    latency_ms=max(0, int((self.monotonic() - started_at) * 1000)),
                    finish_reason=finish_reason,
                    usage=_usage_complete(usages),
                    attempts=attempts,
                )
            except StructuredOutputError as exc:
                failure = _MappedFailure(
                    exc.code,
                    retryable=exc.retryable,
                    category="schema" if exc.code == ErrorCode.LLM_OUTPUT_SCHEMA_INVALID else "parse",
                    safe_detail=exc.safe_detail,
                )
            except _MappedFailure as exc:
                failure = exc
            except Exception as exc:
                failure = _map_exception(exc)

            attempt_latency = max(0, int((self.monotonic() - attempt_started) * 1000))
            attempt_usage = raw.usage if raw else LLMUsage()
            if raw:
                usages.append(raw.usage)
            attempts.append(LLMAttemptSummary(
                attempt=attempt,
                status="retryable_error" if failure.retryable else "failed",
                error_code=failure.code.value,
                latency_ms=attempt_latency,
                structured_output_mode=mode,
                usage=attempt_usage,
            ))

            can_text_fallback = (
                auto_mode
                and mode != StructuredOutputMode.TEXT
                and options.allow_text_fallback
                and failure.code
                in {ErrorCode.LLM_BAD_REQUEST, ErrorCode.LLM_STRUCTURED_OUTPUT_UNSUPPORTED}
            )
            can_repair = (
                options.allow_schema_repair
                and not repair_used
                and failure.code
                in {
                    ErrorCode.LLM_OUTPUT_EMPTY,
                    ErrorCode.LLM_OUTPUT_TRUNCATED,
                    ErrorCode.LLM_OUTPUT_PARSE_FAILED,
                    ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
                }
            )
            output_failure = failure.code in {
                ErrorCode.LLM_OUTPUT_EMPTY,
                ErrorCode.LLM_OUTPUT_TRUNCATED,
                ErrorCode.LLM_OUTPUT_PARSE_FAILED,
                ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
            }
            can_transport_retry = failure.retryable and not output_failure
            if attempt >= options.max_attempts or not (
                can_transport_retry or can_text_fallback or can_repair
            ):
                self._raise_final(
                    failure=failure,
                    context=context,
                    attempt=attempt,
                    started_at=started_at,
                    attempts=attempts,
                    finish_reason=finish_reason,
                )

            if can_text_fallback:
                mode = StructuredOutputMode.TEXT
            elif can_repair and raw is not None:
                repair_used = True
                call_messages = self._repair_messages(
                    call_messages,
                    output_schema,
                    raw.content,
                    failure,
                )
            else:
                delay = self._delay_for(attempt, failure.retry_after)
                remaining = self._remaining_seconds(context)
                if remaining is not None and delay >= remaining:
                    self._raise_final(
                        failure=failure,
                        context=context,
                        attempt=attempt,
                        started_at=started_at,
                        attempts=attempts,
                        finish_reason=finish_reason,
                    )
                self.sleep(delay)

        raise AssertionError("LLMGateway attempt loop exited unexpectedly")


@lru_cache()
def default_llm_gateway() -> LLMGateway:
    """Build the application-wide gateway from validated runtime settings."""

    settings = get_settings()
    return LLMGateway(
        LangChainChatTransport(settings),
        retry_base_delay_seconds=settings.llm_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.llm_retry_max_delay_seconds,
        default_options=LLMCallOptions(
            request_timeout_seconds=settings.llm_request_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            max_output_tokens=settings.llm_max_output_tokens,
            structured_output_mode=StructuredOutputMode(
                settings.llm_structured_output_mode
            ),
        ),
        generator_max_output_tokens=settings.llm_generator_max_output_tokens,
    )
