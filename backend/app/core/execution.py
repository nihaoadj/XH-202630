"""Execution identity shared with persistence, without repository dependencies."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionFence:
    run_id: str
    owner: str
    epoch: int | None = None


_current: ContextVar[ExecutionFence | None] = ContextVar("execution_fence", default=None)


def current_execution_fence() -> ExecutionFence | None:
    return _current.get()


@contextmanager
def execution_fence(value: ExecutionFence):
    token = _current.set(value)
    try:
        yield value
    finally:
        _current.reset(token)
