"""Provider-neutral contract for durable, pre-call round budget reservations."""

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Protocol
import time
import json

from app.models.shared.llm import LLMBudgetScope, LLMCallContext, LLMUsage


class LLMBudgetGuard(Protocol):
    def reserve(self, context: LLMCallContext, attempt: int, tokens: int, runtime_seconds: float = 0) -> str: ...

    def settle(self, reservation_id: str, usage: LLMUsage | None, runtime_seconds: float | None = None) -> None: ...


class LLMBudgetUnavailable(RuntimeError):
    """A scoped model call cannot safely proceed without reserved capacity."""


@dataclass(frozen=True)
class _ActiveScope:
    scope: LLMBudgetScope
    input_cap: int
    guard: LLMBudgetGuard


_active_scope: ContextVar[_ActiveScope | None] = ContextVar("round_llm_budget", default=None)


@contextmanager
def round_call_scope(scope: LLMBudgetScope, input_cap: int, guard: LLMBudgetGuard):
    """Server-only workflow/assessment boundary, isolated across async contexts.

    This scope is never derived from prompts or client constraints. It must
    enclose the actual Gateway calls; worker executors must propagate context
    explicitly when they create their own threads.
    """
    if input_cap <= 0 or guard is None:
        raise LLMBudgetUnavailable("ROUND_BUDGET_NOT_CONFIGURED")
    previous = _active_scope.get()
    if previous is not None and previous.scope != scope:
        raise LLMBudgetUnavailable("ROUND_BUDGET_NESTED_SCOPE_MISMATCH")
    token = _active_scope.set(_ActiveScope(scope, input_cap, guard))
    try:
        yield
    finally:
        _active_scope.reset(token)


def effective_context(context: LLMCallContext) -> LLMCallContext:
    active = _active_scope.get()
    if active is None:
        return context
    if context.budget_scope is not None and context.budget_scope != active.scope:
        raise LLMBudgetUnavailable("ROUND_BUDGET_CONTEXT_MISMATCH")
    return context.model_copy(update={
        "budget_scope": active.scope, "call_purpose": active.scope.kind,
        "budget_input_token_cap": active.input_cap,
    })


def _guard(guard: LLMBudgetGuard | None) -> LLMBudgetGuard | None:
    active = _active_scope.get()
    return active.guard if active is not None else guard


def reserve_call(guard: LLMBudgetGuard | None, context: LLMCallContext, attempt: int, output_cap: int, runtime_seconds: float = 0) -> str | None:
    if context.budget_scope is None:
        return None
    guard = _guard(guard)
    if guard is None or context.budget_input_token_cap is None:
        raise LLMBudgetUnavailable("ROUND_BUDGET_NOT_CONFIGURED")
    return guard.reserve(context, attempt, context.budget_input_token_cap + output_cap, runtime_seconds)


def budgeted_transport_call(invoke, guard: LLMBudgetGuard | None, reservation: str | None, **kwargs):
    guard = _guard(guard)
    raw = None
    started = time.monotonic()
    try:
        active = _active_scope.get()
        if active is not None:
            # A byte-level upper bound is deliberately conservative. Never
            # reserve a small guessed input while sending a larger prompt.
            messages = [message.model_dump(mode="json") if hasattr(message, "model_dump") else str(message)
                        for message in kwargs.get("messages", [])]
            schema = kwargs.get("output_schema")
            envelope = {"messages": messages, "schema": schema.model_json_schema() if schema is not None else {}}
            if len(json.dumps(envelope, ensure_ascii=False).encode("utf-8")) + 4096 > active.input_cap:
                raise LLMBudgetUnavailable("ROUND_INPUT_CAPACITY_EXCEEDED")
        raw = invoke(**kwargs)
        return raw
    finally:
        if reservation is not None:
            guard.settle(reservation, raw.usage if raw is not None else None,
                         max(0, time.monotonic() - started) if raw is not None else None)
