"""Execution identity shared with persistence, without repository dependencies."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import uuid


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


@dataclass(frozen=True)
class ExecutionSession:
    run_id: str
    owner: str
    session_id: str


_session: ContextVar[ExecutionSession | None] = ContextVar("execution_session", default=None)


def current_execution_session() -> ExecutionSession | None:
    return _session.get()


@contextmanager
def execution_session(run_id: str, owner: str):
    """One continuous service invocation, including every in-graph revision."""
    value = ExecutionSession(run_id, owner, uuid.uuid4().hex)
    token = _session.set(value)
    try:
        yield value
    finally:
        _session.reset(token)
