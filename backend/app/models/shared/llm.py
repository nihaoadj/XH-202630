"""Provider-neutral DTOs for bounded, observable LLM calls."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Generic, List, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field


T = TypeVar("T")


class StructuredOutputMode(str, Enum):
    AUTO = "auto"
    JSON_SCHEMA = "json_schema"
    FUNCTION_CALLING = "function_calling"
    JSON_MODE = "json_mode"
    TEXT = "text"


class LLMCallContext(BaseModel):
    run_id: str
    step_id: str
    node_name: str
    schema_name: str
    generation_attempt: int = Field(default=1, ge=1)
    workflow_deadline_at: Optional[datetime] = None
    call_id: str = Field(default_factory=lambda: str(uuid.uuid4()))


class LLMCallOptions(BaseModel):
    temperature: float = Field(default=0.0, ge=0.0, le=2.0)
    max_output_tokens: int = Field(default=4096, ge=1)
    # A bounded second budget for Claim calls that stop because the provider
    # exhausted the first output-token budget. Other nodes leave this unset.
    truncated_retry_output_tokens: Optional[int] = Field(default=None, ge=1)
    request_timeout_seconds: float = Field(default=30.0, gt=0)
    retry_request_timeout_seconds: Optional[float] = Field(default=None, gt=0)
    max_attempts: int = Field(default=2, ge=1, le=3)
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.AUTO
    allow_text_fallback: bool = True
    allow_schema_repair: bool = True
    # Most nodes use one repair turn; Claim nodes may use a second bounded
    # repair because long audits can expose a different validation error after
    # the first correction.
    schema_repair_attempts: int = Field(default=1, ge=0, le=3)


class LLMUsage(BaseModel):
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)


class LLMAttemptSummary(BaseModel):
    attempt: int = Field(ge=1)
    status: str
    error_code: Optional[str] = None
    latency_ms: int = Field(ge=0)
    structured_output_mode: StructuredOutputMode
    usage: LLMUsage = Field(default_factory=LLMUsage)


class RawLLMResponse(BaseModel):
    """Sanitized transport result; content remains in memory and is never logged."""

    content: Any
    response_metadata: Dict[str, Any] = Field(default_factory=dict)
    usage: LLMUsage = Field(default_factory=LLMUsage)
    provider_request_id: Optional[str] = None
    finish_reason: Optional[str] = None
    structured_output_mode: StructuredOutputMode = StructuredOutputMode.TEXT


class LLMCallResult(BaseModel, Generic[T]):
    model_config = ConfigDict(protected_namespaces=())

    output: T
    call_id: str
    model_name: str
    provider_request_id: Optional[str] = None
    structured_output_mode: StructuredOutputMode
    attempt_count: int = Field(ge=1)
    retry_count: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    finish_reason: Optional[str] = None
    usage: LLMUsage = Field(default_factory=LLMUsage)
    attempts: List[LLMAttemptSummary] = Field(default_factory=list)

    def trace_metadata(self) -> Dict[str, Any]:
        """Return the sanitized subset persisted in an Agent trace."""

        return {
            "llm_call_id": self.call_id,
            "model_name": self.model_name,
            "provider_request_id": self.provider_request_id,
            "structured_output_mode": self.structured_output_mode.value,
            "finish_reason": self.finish_reason,
            "input_tokens": self.usage.input_tokens,
            "output_tokens": self.usage.output_tokens,
            "total_tokens": self.usage.total_tokens,
            "llm_duration_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "llm_attempts": [
                {
                    "attempt": item.attempt,
                    "status": item.status,
                    "error_code": item.error_code,
                    "latency_ms": item.latency_ms,
                    "structured_output_mode": item.structured_output_mode.value,
                    "input_tokens": item.usage.input_tokens,
                    "output_tokens": item.usage.output_tokens,
                    "total_tokens": item.usage.total_tokens,
                }
                for item in self.attempts
            ],
        }
