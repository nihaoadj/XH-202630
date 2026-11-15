"""Agent-layer scope adapters for the bypass LLM-call accounting (T41).

These helpers bind task segments, recorded-step stages and resource/scene
attribution around the existing workflow entry points.  They never persist
anything, never touch business state and degrade to no-ops when accounting is
disabled or no scope can be bound safely.
"""

from __future__ import annotations

import contextvars
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from app.core.llm import accounting
from app.models.shared.llm_accounting import AccountingDomain

TEXT_DOMAIN = AccountingDomain.LEARNING_DOCUMENTS
COURSEWARE_DOMAIN = AccountingDomain.COURSEWARE


@contextmanager
def text_run_segment(run_id: str | None) -> Iterator[Any]:
    """One text generation task execution segment (root scope)."""

    with accounting.segment_scope(TEXT_DOMAIN, run_id or "") as segment:
        yield segment


@contextmanager
def courseware_run_segment(run_id: str | None, stage: str | None = None) -> Iterator[Any]:
    """One interactive-courseware execution segment (root scope)."""

    with accounting.segment_scope(COURSEWARE_DOMAIN, run_id or "", stage) as segment:
        yield segment


@contextmanager
def courseware_batch() -> Iterator[Any]:
    """Outermost courseware execution-batch container (Worker/outbox)."""

    with accounting.batch_scope() as batch:
        yield batch


@contextmanager
def recorded_step_scope(step_context: dict[str, Any] | None) -> Iterator[Any]:
    """Bind the step identity preallocated by RecordedNode."""

    if not isinstance(step_context, dict):
        yield None
        return
    with accounting.stage_scope(
        str(step_context.get("node_name") or "unknown"),
        step_id=step_context.get("step_id"),
        sequence=step_context.get("sequence"),
        attribution="task",
    ) as scope:
        yield scope


@contextmanager
def exclusive_resource_scope(labels: Any) -> Iterator[Any]:
    """Attribute subsequent model calls to one exclusive resource/scene."""

    with accounting.resource_scope(labels, shared=False) as scope:
        yield scope


@contextmanager
def shared_resource_scope(labels: Any) -> Iterator[Any]:
    """Attribute subsequent model calls to a shared resource set (Judge)."""

    with accounting.resource_scope(labels, shared=True) as scope:
        yield scope


@contextmanager
def stage_labeled_scope(
    stage: str,
    *,
    labels: Any = None,
    shared: bool = False,
    step_id: str | None = None,
) -> Iterator[Any]:
    """Bind a review/claim/revision stage with optional resource labels."""

    with accounting.stage_scope(
        stage,
        step_id=step_id,
        attribution="resource_set" if shared else ("resource" if labels else "task"),
        labels=labels,
    ) as scope:
        yield scope


def capture_context() -> contextvars.Context:
    """Snapshot the current accounting scope stack for worker threads."""

    return contextvars.copy_context()


def bind_generated_resource(spec_id: Any, resource_id: Any) -> None:
    """Resolve a provisional spec label without affecting business execution."""
    accounting.bind_generated_resource(spec_id, resource_id)


def run_with_captured_context(
    ctx: contextvars.Context, func: Callable[..., Any], *args: Any, **kwargs: Any
) -> Any:
    """Run ``func`` inside a previously captured context (thread pool)."""

    return ctx.run(func, *args, **kwargs)


__all__ = [
    "TEXT_DOMAIN",
    "COURSEWARE_DOMAIN",
    "text_run_segment",
    "courseware_run_segment",
    "courseware_batch",
    "recorded_step_scope",
    "exclusive_resource_scope",
    "shared_resource_scope",
    "stage_labeled_scope",
    "capture_context",
    "bind_generated_resource",
    "run_with_captured_context",
]
