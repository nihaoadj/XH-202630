"""OpenAI-compatible model construction and LangChain transport adapter."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Callable

import httpx
from langchain_core.messages import AIMessage, BaseMessage
from langchain_openai import ChatOpenAI

from app.config import Settings, get_settings
from app.models.llm import LLMUsage, RawLLMResponse, StructuredOutputMode


def create_chat_model(
    *,
    settings: Settings | None = None,
    timeout_seconds: float | None = None,
    max_output_tokens: int | None = None,
    temperature: float = 0.0,
) -> ChatOpenAI:
    """Build one explicitly bounded provider client.

    SDK retries are disabled because LLMGateway owns the only retry budget.
    """

    settings = settings or get_settings()
    # ``trust_env=False`` is intentional.  On Windows, httpx otherwise picks
    # up stale system proxy settings even after the process environment has
    # been cleaned, routing model calls to dead localhost proxy ports.  A
    # deployment that genuinely needs a proxy must set LLM_PROXY_URL, which is
    # explicit, validated and observable configuration.
    http_client = httpx.Client(
        proxy=settings.llm_proxy_url or None,
        trust_env=False,
    )
    return ChatOpenAI(
        api_key=settings.llm_api_key.get_secret_value(),
        base_url=settings.llm_base_url,
        model=settings.llm_model,
        temperature=temperature,
        timeout=timeout_seconds or getattr(settings, "llm_request_timeout_seconds", 30.0),
        max_retries=0,
        max_tokens=max_output_tokens,
        http_client=http_client,
    )


@lru_cache()
def get_llm() -> ChatOpenAI:
    """Compatibility factory for non-Agent callers during the P0-02 migration."""

    return create_chat_model(settings=get_settings(), temperature=0.3)


def _usage_from_message(message: AIMessage) -> LLMUsage:
    usage = message.usage_metadata or {}
    token_usage = message.response_metadata.get("token_usage", {})
    return LLMUsage(
        input_tokens=usage.get("input_tokens", token_usage.get("prompt_tokens")),
        output_tokens=usage.get("output_tokens", token_usage.get("completion_tokens")),
        total_tokens=usage.get("total_tokens", token_usage.get("total_tokens")),
    )


class LangChainChatTransport:
    """Provider-neutral transport backed by the pinned ChatOpenAI adapter."""

    def __init__(
        self,
        settings: Settings | None = None,
        client_factory: Callable[..., ChatOpenAI] = create_chat_model,
    ):
        self.settings = settings or get_settings()
        self.client_factory = client_factory
        self.model_name = self.settings.llm_model

    def invoke(
        self,
        *,
        messages: list[BaseMessage],
        output_schema: type,
        mode: StructuredOutputMode,
        timeout_seconds: float,
        temperature: float,
        max_output_tokens: int,
    ) -> RawLLMResponse:
        client = self.client_factory(
            settings=self.settings,
            timeout_seconds=timeout_seconds,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
        )

        parsed: Any = None
        raw: AIMessage
        if mode == StructuredOutputMode.TEXT:
            raw = client.invoke(messages)
        else:
            runnable = client.with_structured_output(
                output_schema,
                method=mode.value,
                include_raw=True,
            )
            result = runnable.invoke(messages)
            if not isinstance(result, dict) or "raw" not in result:
                raise TypeError("structured transport returned an invalid envelope")
            raw = result["raw"]
            parsed = result.get("parsed")

        if not isinstance(raw, AIMessage):
            raise TypeError("transport expected AIMessage")
        metadata = dict(raw.response_metadata or {})
        if raw.additional_kwargs.get("refusal"):
            metadata["refusal"] = True
        content = parsed if parsed is not None else raw.content
        if parsed is None and not content and len(raw.tool_calls) == 1:
            # Preserve the provider's normalized tool arguments for the one
            # canonical parser; never log or persist this transient payload.
            content = raw.tool_calls[0].get("args")
        return RawLLMResponse(
            content=content,
            response_metadata=metadata,
            usage=_usage_from_message(raw),
            provider_request_id=raw.id or metadata.get("request_id"),
            finish_reason=metadata.get("finish_reason"),
            structured_output_mode=mode,
        )
