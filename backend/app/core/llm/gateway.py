"""Bounded, observable and provider-neutral LLM invocation gateway."""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timezone
from functools import lru_cache
from threading import Event, Thread
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
from app.core.security.errors import ErrorCode, PUBLIC_MESSAGES
from app.core.llm.transport import LangChainChatTransport
from app.core.llm.structured_output import StructuredOutputError, parse_structured_output
from app.models.shared.llm import (
    LLMAttemptSummary,
    LLMCallContext,
    LLMCallOptions,
    LLMCallResult,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from app.models.shared.workflow import ErrorInfo


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
    # LangChain raises this provider-neutral exception when a structured
    # response ends because its output-token budget was exhausted.  It is not
    # an upstream outage: classify it as truncation so the retry path and
    # observability accurately reflect what happened.
    if type(exc).__name__ == "LengthFinishReasonError":
        return _MappedFailure(
            ErrorCode.LLM_OUTPUT_TRUNCATED,
            retryable=True,
            category="parse",
            safe_detail="finish_reason:length",
        )
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
        # Providers and their compatibility adapters can surface transient
        # transport failures as plain RuntimeError/ValueError rather than an
        # OpenAI SDK exception.  Treat an otherwise-unclassified failure as
        # transient within the bounded call budget.  This is especially
        # important for long HTML-guide responses: one adapter hiccup must not
        # immediately turn a recoverable resource into human review.
        retryable=True,
        category="upstream",
        safe_detail=f"unexpected:{type(exc).__name__}",
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


def _invoke_transport_with_hard_timeout(
    transport: LLMTransport,
    *,
    timeout_seconds: float,
    **kwargs: Any,
) -> RawLLMResponse:
    """Bound a synchronous adapter even when its HTTP stack ignores timeout.

    Some OpenAI-compatible adapters accept a custom httpx client but then do
    not reliably propagate the SDK timeout to a blocked socket read.  The
    gateway must still honour its workflow budget.  The worker is daemonized:
    on a provider defect it cannot keep the workflow process alive after the
    gateway has failed closed and applied its bounded retry policy.
    """
    completed = Event()
    outcome: dict[str, Any] = {}

    def invoke() -> None:
        try:
            outcome["value"] = transport.invoke(timeout_seconds=timeout_seconds, **kwargs)
        except Exception as exc:  # mapped by the normal gateway failure path
            outcome["error"] = exc
        finally:
            completed.set()

    Thread(target=invoke, name="llm-transport", daemon=True).start()
    if not completed.wait(timeout=max(0.001, timeout_seconds)):
        raise TimeoutError("llm transport hard timeout")
    if "error" in outcome:
        raise outcome["error"]
    value = outcome.get("value")
    if not isinstance(value, RawLLMResponse):
        raise TypeError("transport returned an invalid response")
    return value


class LLMGateway:
    def __init__(
        self,
        transport: LLMTransport,
        *,
        retry_base_delay_seconds: float = 0.5,
        retry_max_delay_seconds: float = 3.0,
        default_options: LLMCallOptions | None = None,
        resource_generation_max_attempts: int | None = None,
        generator_max_output_tokens: int | None = None,
        resource_generator_max_output_tokens: int | None = None,
        claim_max_attempts: int | None = None,
        claim_max_output_tokens: int | None = None,
        claim_truncated_retry_output_tokens: int | None = None,
        claim_request_timeout_seconds: float | None = None,
        claim_schema_repair_attempts: int | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        jitter: Callable[[], float] = random.random,
    ):
        self.transport = transport
        self.retry_base_delay_seconds = retry_base_delay_seconds
        self.retry_max_delay_seconds = retry_max_delay_seconds
        self.default_options = default_options or LLMCallOptions()
        self.resource_generation_max_attempts = (
            resource_generation_max_attempts
            or self.default_options.max_attempts
        )
        self.generator_max_output_tokens = (
            generator_max_output_tokens or self.default_options.max_output_tokens
        )
        self.resource_generator_max_output_tokens = (
            resource_generator_max_output_tokens
            or self.generator_max_output_tokens
        )
        self.claim_max_attempts = claim_max_attempts or self.default_options.max_attempts
        self.claim_max_output_tokens = (
            claim_max_output_tokens or self.default_options.max_output_tokens
        )
        self.claim_truncated_retry_output_tokens = min(
            claim_truncated_retry_output_tokens
            or self.claim_max_output_tokens * 2,
            65536,
        )
        self.claim_request_timeout_seconds = (
            claim_request_timeout_seconds
            or self.default_options.request_timeout_seconds
        )
        self.claim_schema_repair_attempts = claim_schema_repair_attempts or 2
        self.sleep = sleep
        self.monotonic = monotonic
        self.wall_clock = wall_clock
        self.jitter = jitter

    def options_for(
        self,
        node_name: str,
        *,
        temperature: float = 0.0,
        max_output_tokens: int | None = None,
        request_timeout_seconds: float | None = None,
    ) -> LLMCallOptions:
        """Return one immutable-per-call copy of the configured retry budget."""

        resource_generation_nodes = {
            "text_resource_agent",
            "assessment_agent",
            "practice_guide_agent",
        }
        if node_name in resource_generation_nodes:
            max_tokens = self.resource_generator_max_output_tokens
            configured_timeout_seconds = self.default_options.request_timeout_seconds
        elif node_name in {"claim_extractor", "claim_judge"}:
            max_tokens = self.claim_max_output_tokens
            configured_timeout_seconds = self.claim_request_timeout_seconds
        elif node_name == "generator":
            max_tokens = self.generator_max_output_tokens
            configured_timeout_seconds = self.default_options.request_timeout_seconds
        else:
            max_tokens = self.default_options.max_output_tokens
            configured_timeout_seconds = self.default_options.request_timeout_seconds
        max_attempts = (
            self.resource_generation_max_attempts
            if node_name in (
                resource_generation_nodes
            )
            else self.claim_max_attempts
            if node_name in {"claim_extractor", "claim_judge"}
            else self.default_options.max_attempts
        )
        updates = {
            "temperature": temperature,
            "max_output_tokens": max(1, int(max_output_tokens if max_output_tokens is not None else max_tokens)),
            "request_timeout_seconds": float(request_timeout_seconds if request_timeout_seconds is not None else configured_timeout_seconds),
            "max_attempts": max_attempts,
        }
        if node_name in {"claim_extractor", "claim_judge"}:
            updates["schema_repair_attempts"] = self.claim_schema_repair_attempts
            updates["truncated_retry_output_tokens"] = (
                self.claim_truncated_retry_output_tokens
            )
        return self.default_options.model_copy(update=updates)

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

    @staticmethod
    def _empty_output_recovery_messages(
        messages: list[BaseMessage],
        output_schema: type[BaseModel],
        *,
        recovery_attempt: int,
    ) -> list[BaseMessage]:
        """Ask for a fresh complete response after a provider returned nothing.

        An empty provider response has no partial JSON to repair.  Replaying an
        empty assistant message biases some OpenAI-compatible providers toward
        another empty turn, so recovery deliberately starts from the original
        task messages and adds an explicit completion instruction instead.
        """

        schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "上一轮没有返回任何有效内容。请重新完整生成结果；不得留空、不得省略必填字段，"
            "即使内容较长也必须先返回一个完整、可解析的 JSON 对象。"
            f"这是第 {recovery_attempt} 次空输出恢复。\n"
            f"JSON Schema：{schema}"
        )
        return [SystemMessage(content=instruction), *messages]

    @staticmethod
    def _compact_output_recovery_messages(
        messages: list[BaseMessage],
        output_schema: type[BaseModel],
        *,
        recovery_attempt: int,
    ) -> list[BaseMessage]:
        """Retry a truncated/unparseable response without replaying it verbatim."""

        schema = json.dumps(output_schema.model_json_schema(), ensure_ascii=False)
        instruction = (
            "上一轮输出未能在预算内形成完整 JSON。请从头重新生成一个更紧凑、完整的 JSON 对象；"
            "不得延续上一轮内容，不得解释，不得重复背景。优先保留全部必填字段与可执行步骤，"
            "压缩每个字段的措辞，并在完成最后一个必填字段后立即结束。"
            f"这是第 {recovery_attempt} 次紧凑恢复。\n"
            f"JSON Schema：{schema}"
        )
        return [SystemMessage(content=instruction), *messages]

    @staticmethod
    def _compact_plain_text_recovery_messages(
        messages: list[BaseMessage],
        *,
        content_kind: str,
        recovery_attempt: int,
    ) -> list[BaseMessage]:
        """Retry a length-limited plain-text artifact without changing its format."""

        instruction = (
            "上一轮 Markdown 在输出上限前被截断。请从头输出一份完整但更紧凑的 Markdown，"
            "不要续写上一轮，不要输出 JSON、代码围栏或解释；保留所有要求的标题层级、知识点与"
            "练习，压缩措辞后在总结结束处立即停止。"
            f"这是第 {recovery_attempt} 次紧凑恢复。"
        )
        return [SystemMessage(content=instruction), *messages]

    @staticmethod
    def _json_mode_messages(
        messages: list[BaseMessage],
        output_schema: type[BaseModel],
    ) -> list[BaseMessage]:
        """Supply the provider-required JSON-object and schema instruction.

        DeepSeek's OpenAI-compatible ``json_object`` response format rejects a
        request unless one message explicitly contains the lower-case word
        ``json``.  Keeping that transport compatibility rule here prevents
        individual resource prompts from carrying provider-specific wording.
        JSON mode constrains the wire format only; supplying the compact schema
        on the first provider attempt prevents predictable validation retries.
        """

        schema = json.dumps(
            output_schema.model_json_schema(), ensure_ascii=False, separators=(",", ":"),
        )
        return [
            SystemMessage(
                content=(
                    "Return exactly one valid json object that conforms to this JSON Schema, "
                    "with no surrounding text:\n"
                    f"{schema}"
                )
            ),
            *messages,
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
            "LLM call failed run_id=%s step_id=%s call_id=%s node=%s code=%s category=%s detail=%s attempt=%s retry_count=%s",
            context.run_id,
            context.step_id,
            context.call_id,
            context.node_name,
            failure.code.value,
            failure.category,
            failure.safe_detail,
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
        original_messages = list(messages)
        call_messages = list(original_messages)
        finish_reason: str | None = None
        repair_attempts = 0
        next_output_tokens = options.max_output_tokens

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
            if mode == StructuredOutputMode.TEXT:
                prepared_messages = self._text_messages(call_messages, output_schema)
            elif mode == StructuredOutputMode.JSON_MODE:
                prepared_messages = self._json_mode_messages(call_messages, output_schema)
            else:
                prepared_messages = call_messages
            attempt_started = self.monotonic()
            raw: RawLLMResponse | None = None
            try:
                raw = _invoke_transport_with_hard_timeout(
                    self.transport,
                    timeout_seconds=timeout,
                    messages=prepared_messages,
                    output_schema=output_schema,
                    mode=mode,
                    temperature=options.temperature,
                    max_output_tokens=next_output_tokens,
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
            output_repairable = failure.code in {
                ErrorCode.LLM_OUTPUT_TRUNCATED,
                ErrorCode.LLM_OUTPUT_PARSE_FAILED,
                ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
            }
            can_repair = (
                options.allow_schema_repair
                and output_repairable
                and attempt < options.max_attempts
                and repair_attempts < options.schema_repair_attempts
            )
            can_empty_output_retry = (
                failure.code == ErrorCode.LLM_OUTPUT_EMPTY
                and attempt < options.max_attempts
            )
            output_failure = failure.code in {
                ErrorCode.LLM_OUTPUT_EMPTY,
                ErrorCode.LLM_OUTPUT_TRUNCATED,
                ErrorCode.LLM_OUTPUT_PARSE_FAILED,
                ErrorCode.LLM_OUTPUT_SCHEMA_INVALID,
            }
            can_transport_retry = failure.retryable and not output_failure
            if attempt >= options.max_attempts or not (
                can_transport_retry
                or can_text_fallback
                or can_repair
                or can_empty_output_retry
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
                # Keep output recovery bounded by max_attempts, but permit a
                # second repair after the first repair itself is rejected.
                # Providers can return a different schema violation on the
                # repair turn; stopping after exactly one repair made Claim
                # auditing unnecessarily fragile.
                repair_attempts += 1
                call_messages = self._repair_messages(
                    original_messages,
                    output_schema,
                    raw.content,
                    failure,
                )
                if failure.code == ErrorCode.LLM_OUTPUT_TRUNCATED:
                    next_output_tokens = min(
                        options.truncated_retry_output_tokens
                        or options.max_output_tokens,
                        65536,
                    )
            elif can_repair:
                # A provider can report finish_reason=length before exposing
                # any parseable raw payload.  Retrying the same prompt merely
                # repeats the long response; retry once with an explicit
                # compact-output recovery instruction instead.
                repair_attempts += 1
                call_messages = self._compact_output_recovery_messages(
                    original_messages,
                    output_schema,
                    recovery_attempt=attempt,
                )
                if failure.code == ErrorCode.LLM_OUTPUT_TRUNCATED:
                    next_output_tokens = min(
                        options.truncated_retry_output_tokens
                        or options.max_output_tokens,
                        65536,
                    )
            elif can_empty_output_retry:
                call_messages = self._empty_output_recovery_messages(
                    original_messages,
                    output_schema,
                    recovery_attempt=attempt,
                )
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

    def invoke_plain_text(
        self,
        *,
        messages: list[BaseMessage],
        context: LLMCallContext,
        options: LLMCallOptions,
    ) -> LLMCallResult[str]:
        """Invoke a bounded Markdown/text generation without a JSON wrapper.

        Long learning documents should not be encoded as one escaped JSON
        string.  Besides wasting output tokens, that made a provider length
        stop indistinguishable from a malformed resource.  This path retains
        the gateway's timeout, retry and trace guarantees while returning the
        model's plain text directly.
        """

        started_at = self.monotonic()
        attempts: list[LLMAttemptSummary] = []
        usages: list[LLMUsage] = []
        original_messages = list(messages)
        call_messages = list(original_messages)
        finish_reason: str | None = None
        compact_retry_used = False

        for attempt in range(1, options.max_attempts + 1):
            remaining = self._remaining_seconds(context)
            if remaining is not None and remaining <= 0:
                self._raise_final(
                    failure=_MappedFailure(ErrorCode.LLM_TIMEOUT, retryable=True,
                                           category="timeout", safe_detail="workflow_deadline_exhausted"),
                    context=context, attempt=attempt, started_at=started_at,
                    attempts=attempts, finish_reason=finish_reason,
                )
            timeout = options.request_timeout_seconds
            if remaining is not None:
                timeout = min(timeout, max(0.001, remaining))
            attempt_started = self.monotonic()
            raw: RawLLMResponse | None = None
            try:
                raw = _invoke_transport_with_hard_timeout(
                    self.transport,
                    timeout_seconds=timeout,
                    messages=call_messages,
                    # TEXT mode never reads this schema; the parameter keeps
                    # the transport protocol shared with structured calls.
                    output_schema=BaseModel,
                    mode=StructuredOutputMode.TEXT,
                    temperature=options.temperature,
                    max_output_tokens=options.max_output_tokens,
                )
                finish_reason = raw.finish_reason
                if raw.response_metadata.get("refusal") or finish_reason == "content_filter":
                    raise _MappedFailure(ErrorCode.LLM_CONTENT_REFUSED, retryable=False,
                                         category="content")
                if finish_reason == "length":
                    raise _MappedFailure(ErrorCode.LLM_OUTPUT_TRUNCATED, retryable=True,
                                         category="parse", safe_detail="finish_reason:length")
                if isinstance(raw.content, str):
                    content = raw.content.strip()
                elif isinstance(raw.content, dict):
                    # Keep the plain-text gateway tolerant of older provider
                    # adapters that still wrap Markdown in a structured
                    # ``markdown_content``/``content`` field.
                    content = next(
                        (
                            str(raw.content[key]).strip()
                            for key in ("markdown_content", "content", "text")
                            if isinstance(raw.content.get(key), str)
                        ),
                        "",
                    )
                else:
                    content = ""
                if not content:
                    raise _MappedFailure(ErrorCode.LLM_OUTPUT_EMPTY, retryable=True,
                                         category="parse")
                latency_ms = max(0, int((self.monotonic() - attempt_started) * 1000))
                usages.append(raw.usage)
                attempts.append(LLMAttemptSummary(
                    attempt=attempt, status="success", latency_ms=latency_ms,
                    structured_output_mode=StructuredOutputMode.TEXT, usage=raw.usage,
                ))
                return LLMCallResult(
                    output=content, call_id=context.call_id, model_name=self.transport.model_name,
                    provider_request_id=raw.provider_request_id,
                    structured_output_mode=StructuredOutputMode.TEXT,
                    attempt_count=attempt, retry_count=attempt - 1,
                    latency_ms=max(0, int((self.monotonic() - started_at) * 1000)),
                    finish_reason=finish_reason, usage=_usage_complete(usages), attempts=attempts,
                )
            except _MappedFailure as exc:
                failure = exc
            except Exception as exc:
                failure = _map_exception(exc)

            latency_ms = max(0, int((self.monotonic() - attempt_started) * 1000))
            if raw:
                usages.append(raw.usage)
            attempts.append(LLMAttemptSummary(
                attempt=attempt, status="retryable_error" if failure.retryable else "failed",
                error_code=failure.code.value, latency_ms=latency_ms,
                structured_output_mode=StructuredOutputMode.TEXT,
                usage=raw.usage if raw else LLMUsage(),
            ))
            can_compact_retry = (
                failure.code == ErrorCode.LLM_OUTPUT_TRUNCATED and not compact_retry_used
            )
            can_retry = failure.retryable and failure.code != ErrorCode.LLM_OUTPUT_TRUNCATED
            if attempt >= options.max_attempts or not (can_compact_retry or can_retry):
                self._raise_final(failure=failure, context=context, attempt=attempt,
                                  started_at=started_at, attempts=attempts,
                                  finish_reason=finish_reason)
            if can_compact_retry:
                compact_retry_used = True
                call_messages = self._compact_plain_text_recovery_messages(
                    original_messages,
                    content_kind="markdown",
                    recovery_attempt=attempt,
                )
            delay = self._delay_for(attempt, failure.retry_after)
            remaining = self._remaining_seconds(context)
            if remaining is not None and delay >= remaining:
                self._raise_final(failure=failure, context=context, attempt=attempt,
                                  started_at=started_at, attempts=attempts,
                                  finish_reason=finish_reason)
            self.sleep(delay)

        raise AssertionError("LLMGateway plain-text attempt loop exited unexpectedly")


@lru_cache()
def default_llm_gateway() -> LLMGateway:
    """Build the application-wide gateway from validated runtime settings."""

    settings = get_settings()
    return LLMGateway(
        LangChainChatTransport(settings),
        retry_base_delay_seconds=settings.llm_retry_base_delay_seconds,
        retry_max_delay_seconds=settings.llm_retry_max_delay_seconds,
        resource_generation_max_attempts=(
            settings.llm_resource_generation_max_attempts
        ),
        default_options=LLMCallOptions(
            request_timeout_seconds=settings.llm_request_timeout_seconds,
            max_attempts=settings.llm_max_attempts,
            max_output_tokens=settings.llm_max_output_tokens,
            structured_output_mode=StructuredOutputMode(
                settings.llm_structured_output_mode
            ),
        ),
        generator_max_output_tokens=settings.llm_generator_max_output_tokens,
        resource_generator_max_output_tokens=(
            settings.llm_resource_generator_max_output_tokens
        ),
        claim_max_attempts=settings.claim_max_attempts,
        claim_max_output_tokens=settings.claim_max_output_tokens,
        claim_truncated_retry_output_tokens=settings.claim_truncated_retry_output_tokens,
        claim_request_timeout_seconds=settings.claim_request_timeout_seconds,
        claim_schema_repair_attempts=settings.claim_schema_repair_attempts,
    )
