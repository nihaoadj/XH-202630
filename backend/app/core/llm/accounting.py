"""Bypass LLM-call accounting: in-memory observation scopes and decorators.

The module is the single shared observation point for the real
``LLMGateway.invoke_structured`` / ``invoke_plain_text`` entry points and the
transport hard-timeout helper.  It must never change business behaviour:

* wrappers keep the original function object (``functools.wraps``), pass the
  original argument objects through unchanged, and return or raise the exact
  original result/exception;
* every capture step is fail-safe: an accounting failure degrades to a no-op
  plus a sticky ``incomplete`` marker and never propagates to business code;
* without an active scope stack every decorator is a direct passthrough.

Only standard-library and ``app.models`` imports are allowed here; the
publisher protocol is injectable so no service/persistence layer is imported.
"""

from __future__ import annotations

import contextvars
import functools
import itertools
import logging
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Protocol

from app.models.shared.llm_accounting import (
    AccountingDomain,
    AccountingSegmentV1,
    Attribution,
    LLM_ACCOUNTING_SCHEMA_VERSION,
    LLMAttemptEvidenceV1,
    LLMCallObservationV1,
    MAX_ATTEMPTS_PER_CALL,
    MAX_CALLS_PER_SEGMENT,
    MAX_IDENTITY_CHARS,
    MAX_LONG_IDENTITY_CHARS,
    MAX_MODEL_CHARS,
    MAX_RESOURCE_LABELS,
    SegmentSubmissionV1,
    canonical_accounting_hash,
)

logger = logging.getLogger(__name__)

_PROCESS_NONCE = f"proc-{os.getpid()}-{uuid.uuid4().hex[:8]}"
_SEGMENT_SEQUENCE = itertools.count(1)


class LLMCallAccountingPublisher(Protocol):
    """Injectable sink for sealed segment snapshots (never blocks business)."""

    def submit(self, submission: SegmentSubmissionV1) -> bool: ...


_publisher: LLMCallAccountingPublisher | None = None
_enabled: bool | None = None
_enable_lock = threading.Lock()


def install_publisher(publisher: LLMCallAccountingPublisher | None) -> None:
    global _publisher
    _publisher = publisher


def uninstall_publisher() -> None:
    global _publisher
    _publisher = None


def set_enabled(value: bool) -> None:
    global _enabled
    _enabled = bool(value)


def is_enabled() -> bool:
    global _enabled
    if _enabled is not None:
        return _enabled
    try:
        from app.config import get_settings

        _enabled = bool(getattr(get_settings(), "llm_accounting_enabled", True))
    except Exception:
        _enabled = True
    return _enabled


def _bounded(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value)
    if not text:
        return None
    return text[:limit]


def _safe_label(labels: Any) -> list[str]:
    if not labels:
        return []
    if isinstance(labels, str):
        labels = [labels]
    result: list[str] = []
    for label in labels:
        text = _bounded(label, MAX_LONG_IDENTITY_CHARS)
        if text and text not in result:
            result.append(text)
        if len(result) >= MAX_RESOURCE_LABELS:
            break
    return result


class _BatchFrame:
    """Outermost execution-batch container; owns deferred submission."""

    kind = "batch"

    def __init__(self) -> None:
        self.closed = False
        self.submissions: list[SegmentSubmissionV1] = []
        self.reasons: list[str] = []
        self._lock = threading.Lock()

    def accept(self, submission: SegmentSubmissionV1) -> bool:
        with self._lock:
            if self.closed:
                return False
            self.submissions.append(submission)
            return True

    def flush(self) -> list[SegmentSubmissionV1]:
        with self._lock:
            self.closed = True
            submissions = list(self.submissions)
            self.submissions = []
        for submission in submissions:
            _submit_safely(submission)
        return submissions


class _SegmentFrame:
    """One observed execution segment bound to (domain, run_id)."""

    kind = "segment"

    def __init__(self, domain: AccountingDomain, run_id: str, stage: str | None) -> None:
        self.domain = domain.value
        self.run_id = _bounded(run_id, MAX_LONG_IDENTITY_CHARS) or "unknown"
        self.segment_id = f"{_PROCESS_NONCE}-seg-{next(_SEGMENT_SEQUENCE)}"
        self.stage = _bounded(stage, MAX_IDENTITY_CHARS)
        self.closed = False
        self.calls: list[LLMCallObservationV1] = []
        self.reasons: list[str] = []
        self.capacity_exceeded = False
        self._lock = threading.Lock()
        self._call_ids = itertools.count(1)

    # -- call lifecycle ---------------------------------------------------
    def open_call(self) -> "_CallFrame | None":
        try:
            if self.closed:
                return None
            observation_id = next(self._call_ids)
            if observation_id > MAX_CALLS_PER_SEGMENT:
                self.capacity_exceeded = True
                return None
            return _CallFrame(self, observation_id)
        except Exception:
            self._mark_incomplete("capture_open_failed")
            return None

    def close_call(self, call_frame: "_CallFrame") -> None:
        try:
            observation = call_frame.finalize()
            if observation is None:
                self._mark_incomplete("capture_finalize_failed")
                return
            with self._lock:
                if len(self.calls) >= MAX_CALLS_PER_SEGMENT:
                    self.capacity_exceeded = True
                    return
                self.calls.append(observation)
        except Exception:
            self._mark_incomplete("capture_close_failed")

    def _mark_incomplete(self, reason: str) -> None:
        try:
            with self._lock:
                self.reasons.append(_bounded(reason, 64) or "unknown")
        except Exception:
            pass

    # -- segment lifecycle ------------------------------------------------
    def seal(self) -> AccountingSegmentV1:
        with self._lock:
            self.closed = True
            calls = list(self.calls)
            reasons = list(dict.fromkeys(self.reasons))
            capacity = self.capacity_exceeded
        if capacity:
            reasons = list(dict.fromkeys(reasons + ["capacity_exceeded"]))
        return AccountingSegmentV1(
            domain=self.domain,
            run_id=self.run_id,
            segment_id=self.segment_id,
            process_nonce=_PROCESS_NONCE,
            stage=self.stage,
            calls=calls,
            call_count=len(calls),
            sealed=True,
            capacity_exceeded=capacity,
            incomplete_reasons=reasons,
            recorded_at=datetime.now(timezone.utc).isoformat(),
        )


class _ScopeFrame:
    """Step / stage / resource attribution scope inside a segment."""

    kind = "scope"

    def __init__(
        self,
        *,
        stage: str | None,
        step_id: str | None = None,
        sequence: int | None = None,
        attribution: Attribution = "task",
        labels: list[str] | None = None,
    ) -> None:
        self.stage = _bounded(stage, MAX_IDENTITY_CHARS)
        self.step_id = _bounded(step_id, MAX_LONG_IDENTITY_CHARS)
        self.sequence = sequence
        self.attribution = attribution
        self.labels = _safe_label(labels)


class _CallFrame:
    """Per logical gateway call capture state (thread-confined)."""

    def __init__(self, segment: _SegmentFrame, observation_id: int) -> None:
        self.segment = segment
        self.observation_id = observation_id
        self.capture_complete = True
        self.context: dict[str, Any] = {}
        self.scope: _ScopeFrame | None = None
        self.outcome: str = "success"
        self.error_code: str | None = None
        self.error_class: str | None = None
        self.model_name: str | None = None
        self.structured_mode: str | None = None
        self.gateway_retry_count: int | None = None
        self.top_usage: dict[str, int | None] = {}
        self.summary_attempts: dict[int, dict[str, Any]] = {}
        self.helper_attempts: dict[int, dict[str, Any]] = {}
        self.helper_sequence = itertools.count(1)
        self.attempt_incomplete = False

    # -- transport helper evidence (never raises) --------------------------
    def record_helper_error(self, error_class: str) -> None:
        try:
            ordinal = next(self.helper_sequence)
            if len(self.helper_attempts) >= MAX_ATTEMPTS_PER_CALL * 2:
                return
            self.helper_attempts[ordinal] = {
                "helper_observed": True,
                "helper_error_class": _bounded(error_class, MAX_IDENTITY_CHARS),
                "helper_raw_success": False,
            }
            self.attempt_incomplete = True
        except Exception:
            self.capture_complete = False

    def record_helper_success(self, raw: Any) -> None:
        try:
            ordinal = next(self.helper_sequence)
            if len(self.helper_attempts) >= MAX_ATTEMPTS_PER_CALL * 2:
                return
            usage = getattr(raw, "usage", None)
            self.helper_attempts[ordinal] = {
                "helper_observed": True,
                "helper_raw_success": True,
                "helper_input": getattr(usage, "input_tokens", None) if usage else None,
                "helper_output": getattr(usage, "output_tokens", None) if usage else None,
                "helper_total": getattr(usage, "total_tokens", None) if usage else None,
                "helper_provider_request_id": _bounded(
                    getattr(raw, "provider_request_id", None), MAX_LONG_IDENTITY_CHARS
                ),
                "helper_finish_reason": _bounded(getattr(raw, "finish_reason", None), MAX_IDENTITY_CHARS),
            }
        except Exception:
            self.capture_complete = False

    # -- gateway-level evidence -------------------------------------------
    def record_entry(self, call_context: Any) -> None:
        try:
            self.context = {
                "source_call_id": _bounded(getattr(call_context, "call_id", None), MAX_LONG_IDENTITY_CHARS),
                "run_id": _bounded(getattr(call_context, "run_id", None), MAX_LONG_IDENTITY_CHARS),
                "step_id": _bounded(getattr(call_context, "step_id", None), MAX_LONG_IDENTITY_CHARS),
                "node_name": _bounded(getattr(call_context, "node_name", None), MAX_IDENTITY_CHARS),
                "schema_name": _bounded(getattr(call_context, "schema_name", None), MAX_IDENTITY_CHARS),
                "generation_attempt": getattr(call_context, "generation_attempt", None),
            }
        except Exception:
            self.capture_complete = False

    def record_result(self, result: Any) -> None:
        try:
            self.outcome = "success"
            self.model_name = _bounded(getattr(result, "model_name", None), MAX_MODEL_CHARS)
            mode = getattr(result, "structured_output_mode", None)
            self.structured_mode = _bounded(getattr(mode, "value", mode), MAX_IDENTITY_CHARS)
            self.gateway_retry_count = getattr(result, "retry_count", None)
            self.top_usage = _usage_fields(getattr(result, "usage", None))
            for summary in getattr(result, "attempts", None) or []:
                ordinal = int(getattr(summary, "attempt", len(self.summary_attempts) + 1))
                if len(self.summary_attempts) < MAX_ATTEMPTS_PER_CALL:
                    self.summary_attempts[ordinal] = _summary_fields(summary)
                else:
                    self.capture_complete = False
        except Exception:
            self.capture_complete = False

    def record_gateway_error(self, exc: Exception) -> None:
        try:
            self.outcome = "gateway_error"
            error = getattr(exc, "error", None)
            self.error_code = _bounded(getattr(error, "code", None), MAX_IDENTITY_CHARS)
            self.model_name = _bounded(getattr(exc, "model_name", None), MAX_MODEL_CHARS)
            mode = getattr(exc, "structured_output_mode", None)
            self.structured_mode = _bounded(getattr(mode, "value", mode), MAX_IDENTITY_CHARS)
            self.gateway_retry_count = getattr(exc, "retry_count", None)
            self.top_usage = _usage_fields(getattr(exc, "usage", None))
            for summary in getattr(exc, "attempts", None) or []:
                ordinal = int(getattr(summary, "attempt", len(self.summary_attempts) + 1))
                if len(self.summary_attempts) < MAX_ATTEMPTS_PER_CALL:
                    self.summary_attempts[ordinal] = _summary_fields(summary)
                else:
                    self.capture_complete = False
        except Exception:
            self.capture_complete = False

    def record_exception(self, exc: Exception) -> None:
        try:
            self.outcome = "exception"
            self.error_class = _bounded(type(exc).__name__, MAX_IDENTITY_CHARS)
        except Exception:
            self.capture_complete = False

    # -- finalization -----------------------------------------------------
    def finalize(self) -> LLMCallObservationV1 | None:
        try:
            return self._finalize()
        except Exception:
            self.capture_complete = False
            return None

    def _finalize(self) -> LLMCallObservationV1:
        scope = self.scope
        summary_keys = set(self.summary_attempts)
        helper_keys = set(self.helper_attempts)
        evidence: list[LLMAttemptEvidenceV1] = []
        known = {"input": 0, "output": 0, "total": 0}
        usage_known_all = True
        mismatch = False
        for ordinal in sorted(summary_keys | helper_keys):
            summary = self.summary_attempts.get(ordinal, {})
            helper = self.helper_attempts.get(ordinal, {})
            usage_input = summary.get("usage_input")
            usage_output = summary.get("usage_output")
            usage_total = summary.get("usage_total")
            helper_input = helper.get("helper_input")
            helper_output = helper.get("helper_output")
            helper_total = helper.get("helper_total")
            if (
                usage_input is not None and helper_input is not None and usage_input != helper_input
            ) or (
                usage_output is not None and helper_output is not None and usage_output != helper_output
            ) or (
                usage_total is not None and helper_total is not None and usage_total != helper_total
            ):
                mismatch = True
                evidence_input = evidence_output = evidence_total = None
                source: Any = "conflict"
            else:
                evidence_input = usage_input if usage_input is not None else helper_input
                evidence_output = usage_output if usage_output is not None else helper_output
                evidence_total = usage_total if usage_total is not None else helper_total
                if usage_input is not None and helper_input is not None:
                    source = "both"
                elif usage_input is not None or usage_output is not None or usage_total is not None:
                    source = "summary"
                elif helper_input is not None or helper_output is not None or helper_total is not None:
                    source = "raw"
                else:
                    source = "none"
            if evidence_input is None or evidence_output is None or evidence_total is None:
                usage_known_all = False
            for key, value in (("input", evidence_input), ("output", evidence_output), ("total", evidence_total)):
                if value is not None:
                    known[key] += value
            helper_only = ordinal not in summary_keys
            evidence.append(
                LLMAttemptEvidenceV1(
                    ordinal=ordinal,
                    gateway_status=summary.get("status"),
                    error_code=summary.get("error_code"),
                    error_category=summary.get("error_category"),
                    latency_ms=summary.get("latency_ms"),
                    structured_output_mode=summary.get("mode"),
                    usage_input_tokens=evidence_input,
                    usage_output_tokens=evidence_output,
                    usage_total_tokens=evidence_total,
                    usage_source=source,
                    provider_request_id=summary.get("provider_request_id") or helper.get(
                        "helper_provider_request_id"
                    ),
                    helper_observed=bool(helper.get("helper_observed")),
                    helper_error_class=helper.get("helper_error_class"),
                    helper_raw_success=bool(helper.get("helper_raw_success")),
                    helper_usage_input_tokens=helper.get("helper_input"),
                    helper_usage_output_tokens=helper.get("helper_output"),
                    helper_usage_total_tokens=helper.get("helper_total"),
                    helper_provider_request_id=helper.get("helper_provider_request_id"),
                    helper_finish_reason=helper.get("helper_finish_reason"),
                )
            )
            if helper_only and not helper.get("helper_raw_success"):
                self.attempt_incomplete = True

        top_input, top_output, top_total = (
            self.top_usage.get("input"),
            self.top_usage.get("output"),
            self.top_usage.get("total"),
        )
        complete_usage = (
            usage_known_all
            and not mismatch
            and top_input is not None
            and top_output is not None
            and top_total is not None
            and known["input"] == top_input
            and known["output"] == top_output
            and known["total"] == top_total
        )
        attempt_complete = not self.attempt_incomplete
        attribution: Attribution = "unknown"
        attribution_complete = False
        labels: list[str] = []
        if scope is not None:
            attribution = scope.attribution
            labels = list(scope.labels)
            attribution_complete = True
        context = self.context
        run_id = context.get("run_id") or self.segment.run_id
        duration = sum(
            item.get("latency_ms") or 0
            for item in self.summary_attempts.values()
        )
        def field_complete(key, top):
            return (self.capture_complete and attempt_complete and not mismatch and top is not None
                    and all(getattr(item, "usage_" + key + "_tokens") is not None for item in evidence)
                    and known[key] == top)

        observation = LLMCallObservationV1(
            domain=self.segment.domain,
            run_id=run_id or self.segment.run_id,
            segment_id=self.segment.segment_id,
            observation_id=self.observation_id,
            source_call_id=context.get("source_call_id"),
            stage=scope.stage if scope is not None else self.segment.stage,
            step_id=(scope.step_id if scope is not None else None) or context.get("step_id"),
            stage_sequence=scope.sequence if scope is not None else None,
            node_name=context.get("node_name"),
            schema_name=context.get("schema_name"),
            model_name=self.model_name,
            structured_output_mode=self.structured_mode,
            attribution=attribution,
            resource_labels=labels,
            attempts=evidence,
            observed_attempt_count=len(summary_keys | helper_keys),
            gateway_attempt_count=len(summary_keys) if summary_keys else None,
            gateway_retry_count=self.gateway_retry_count,
            outcome=self.outcome,  # type: ignore[arg-type]
            error_code=self.error_code,
            error_class=self.error_class,
            usage_input_tokens=top_input if field_complete("input", top_input) else None,
            usage_output_tokens=top_output if field_complete("output", top_output) else None,
            usage_total_tokens=top_total if field_complete("total", top_total) else None,
            known_input_tokens=known["input"],
            known_output_tokens=known["output"],
            known_total_tokens=known["total"],
            usage_complete=complete_usage and self.capture_complete and attempt_complete,
            usage_mismatch=mismatch,
            known_llm_duration_ms=duration,
            capture_complete=self.capture_complete,
            attempt_complete=attempt_complete,
            attribution_complete=attribution_complete,
        )
        return observation


def _usage_fields(usage: Any) -> dict[str, int | None]:
    if usage is None:
        return {"input": None, "output": None, "total": None}
    return {
        "input": getattr(usage, "input_tokens", None),
        "output": getattr(usage, "output_tokens", None),
        "total": getattr(usage, "total_tokens", None),
    }


def _summary_fields(summary: Any) -> dict[str, Any]:
    mode = getattr(summary, "structured_output_mode", None)
    return {
        "status": _bounded(getattr(summary, "status", None), MAX_IDENTITY_CHARS),
        "error_code": _bounded(getattr(summary, "error_code", None), MAX_IDENTITY_CHARS),
        "error_category": None,
        "latency_ms": getattr(summary, "latency_ms", None),
        "mode": _bounded(getattr(mode, "value", mode), MAX_IDENTITY_CHARS),
        "usage_input": getattr(summary, "usage", None) and getattr(summary.usage, "input_tokens", None),
        "usage_output": getattr(summary, "usage", None) and getattr(summary.usage, "output_tokens", None),
        "usage_total": getattr(summary, "usage", None) and getattr(summary.usage, "total_tokens", None),
    }


# ---------------------------------------------------------------------------
# Scope stack (ContextVar of immutable tuples; worker threads inherit a copy)
# ---------------------------------------------------------------------------

_STACK: contextvars.ContextVar[tuple[Any, ...]] = contextvars.ContextVar(
    "llm_accounting_scope_stack", default=()
)
_CURRENT_CALL: contextvars.ContextVar[_CallFrame | None] = contextvars.ContextVar(
    "llm_accounting_current_call", default=None
)


def current_stack() -> tuple[Any, ...]:
    return _STACK.get()


def _current_segment() -> _SegmentFrame | None:
    for frame in reversed(_STACK.get()):
        if isinstance(frame, _SegmentFrame) and not frame.closed:
            return frame
    return None


def _current_batch() -> _BatchFrame | None:
    for frame in reversed(_STACK.get()):
        if isinstance(frame, _BatchFrame) and not frame.closed:
            return frame
    return None


def _innermost_scope() -> _ScopeFrame | None:
    for frame in reversed(_STACK.get()):
        if isinstance(frame, _ScopeFrame):
            return frame
    return None


def _safe(action, *args, default=None, **kwargs):
    """Never let observer infrastructure replace a business result or error."""
    try:
        return action(*args, **kwargs)
    except Exception:
        return default


def bind_generated_resource(spec_id: Any, resource_id: Any) -> None:
    """Resolve provisional generation labels after materialization, fail-safe.

    Only unresolved calls in the current segment are updated. Previously
    materialized revisions retain their identity; no business IDs are created.
    """
    segment = None
    try:
        if not is_enabled():
            return
        segment = _current_segment()
        source = _bounded(spec_id, MAX_LONG_IDENTITY_CHARS)
        target = _bounded(resource_id, MAX_LONG_IDENTITY_CHARS)
        if segment is None or not source or not target:
            return
        with segment._lock:
            if segment.closed:
                return
            segment.calls = [
                call.model_copy(update={"resource_labels": [target, *call.resource_labels[1:]]})
                if call.stage in {None, "generate", "generator"} and call.attribution == "resource"
                and call.resource_labels and call.resource_labels[0] == source else call
                for call in segment.calls
            ]
    except Exception:
        if segment is not None:
            _safe(segment._mark_incomplete, "resource_binding_failed")


def _reset(var, token, fallback):
    try:
        var.reset(token)
    except Exception:
        _safe(var.set, fallback)


@contextmanager
def batch_scope():
    existing = _safe(_current_batch)
    batch = None
    token = None
    if _safe(is_enabled, default=False) and existing is None:
        try:
            batch = _BatchFrame()
            token = _STACK.set(_STACK.get() + (batch,))
        except Exception:
            batch = None
    try:
        yield existing or batch
    finally:
        if batch is not None:
            _reset(_STACK, token, ())
            _safe(batch.flush)


@contextmanager
def segment_scope(domain, run_id, stage=None):
    segment = None
    existing = None
    token = None
    if _safe(is_enabled, default=False) and run_id:
        try:
            existing = next((f for f in reversed(_STACK.get())
                if isinstance(f, _SegmentFrame) and not f.closed
                and f.domain == domain.value and f.run_id == str(run_id)[:MAX_LONG_IDENTITY_CHARS]), None)
            if existing is None:
                segment = _SegmentFrame(domain, run_id, stage)
                token = _STACK.set(_STACK.get() + (segment,))
        except Exception:
            segment = None
    try:
        yield existing or segment
    finally:
        if segment is not None:
            # No return in finally: the original business exception must propagate.
            segment.closed = True
            _reset(_STACK, token, ())
            _safe(_finish_segment, segment)


def _finish_segment(segment):
    snapshot = segment.seal()
    submission = SegmentSubmissionV1(segment=snapshot,
        payload_hash=canonical_accounting_hash(snapshot.stable_payload()))
    batch = _current_batch()
    if batch is not None:
        batch.accept(submission)
    else:
        _submit_safely(submission)


@contextmanager
def stage_scope(stage, *, step_id=None, sequence=None, attribution="task", labels=None):
    scope = None
    token = None
    segment = _safe(_current_segment)
    if segment is not None and _safe(is_enabled, default=False):
        try:
            parent = _innermost_scope()
            scope = _ScopeFrame(stage=stage,
                step_id=step_id if step_id is not None else (parent.step_id if parent else None),
                sequence=sequence if sequence is not None else (parent.sequence if parent else None),
                attribution=attribution, labels=labels)
            token = _STACK.set(_STACK.get() + (scope,))
        except Exception:
            _safe(segment._mark_incomplete, "scope_setup_failed")
            scope = None
    try:
        yield scope
    finally:
        if scope is not None:
            _reset(_STACK, token, ())


@contextmanager
def resource_scope(labels: Any, *, shared: bool = False) -> Iterator[_ScopeFrame | None]:
    """Bind an exclusive (or shared) resource/scene/batch attribution scope.

    Stage identity is inherited from the nearest enclosing step scope so a
    resource-level frame never loses its workflow stage grouping.
    """

    attribution: Attribution = "resource_set" if shared else "resource"
    parent = _safe(_innermost_scope)
    with stage_scope(
        parent.stage if parent is not None else None,
        step_id=parent.step_id if parent is not None else None,
        sequence=parent.sequence if parent is not None else None,
        attribution=attribution,
        labels=labels,
    ) as scope:
        yield scope


def _submit_safely(submission: SegmentSubmissionV1) -> bool:
    if _publisher is None:
        return False
    try:
        return bool(_publisher.submit(submission))
    except Exception:
        _safe(logger.warning, "llm-accounting publisher submit failed segment=%s",
              submission.segment.segment_id)
        return False


# ---------------------------------------------------------------------------
# Gateway / transport decorators (the only accounting entry points)
# ---------------------------------------------------------------------------

_GatewayT = Any


def _observe(frame, action, *args):
    try:
        action(*args)
    except Exception:
        frame.capture_complete = False
        _safe(frame.segment._mark_incomplete, "capture_record_failed")


def observed_gateway_method(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap one public LLMGateway method; never alters its behaviour."""

    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        segment = _safe(_current_segment)
        if segment is None or not _safe(is_enabled, default=False):
            return original(*args, **kwargs)
        try:
            call_frame = segment.open_call()
            if call_frame is not None:
                call_frame.scope = _innermost_scope()
                call_frame.record_entry(kwargs.get("context"))
        except Exception:
            _safe(segment._mark_incomplete, "capture_setup_failed")
            call_frame = None
        if call_frame is None:
            return original(*args, **kwargs)
        try:
            token = _CURRENT_CALL.set(call_frame)
        except Exception:
            _safe(segment._mark_incomplete, "capture_bind_failed")
            return original(*args, **kwargs)
        try:
            try:
                result = original(*args, **kwargs)
            except Exception as exc:
                if _looks_like_gateway_error(exc):
                    _observe(call_frame, call_frame.record_gateway_error, exc)
                else:
                    _observe(call_frame, call_frame.record_exception, exc)
                raise
            _observe(call_frame, call_frame.record_result, result)
            return result
        finally:
            _reset(_CURRENT_CALL, token, None)
            _safe(segment.close_call, call_frame)

    return wrapper


def _looks_like_gateway_error(exc: Exception) -> bool:
    return hasattr(exc, "error") and hasattr(exc, "attempts") and hasattr(exc, "retry_count")


def observed_transport_call(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap the hard-timeout transport helper; never enters its inner thread."""

    @functools.wraps(original)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        call_frame = _safe(_CURRENT_CALL.get)
        if call_frame is None or not _safe(is_enabled, default=False):
            return original(*args, **kwargs)
        try:
            result = original(*args, **kwargs)
        except Exception as exc:
            _observe(call_frame, call_frame.record_helper_error, type(exc).__name__)
            raise
        _observe(call_frame, call_frame.record_helper_success, result)
        return result

    return wrapper


def new_segment_id() -> str:
    return f"{_PROCESS_NONCE}-seg-{next(_SEGMENT_SEQUENCE)}"


__all__ = [
    "AccountingDomain",
    "LLM_ACCOUNTING_SCHEMA_VERSION",
    "LLMCallAccountingPublisher",
    "batch_scope",
    "install_publisher",
    "is_enabled",
    "observed_gateway_method",
    "observed_transport_call",
    "resource_scope",
    "segment_scope",
    "set_enabled",
    "stage_scope",
    "uninstall_publisher",
    "current_stack",
    "new_segment_id",
    "_CallFrame",
    "_SegmentFrame",
    "_BatchFrame",
    "_ScopeFrame",
    "_CURRENT_CALL",
    "_STACK",
]
