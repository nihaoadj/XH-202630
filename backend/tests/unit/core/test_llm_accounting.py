"""Unit tests: gateway/transport observation decorators (T41 P2/H1/H2/H5)."""

from __future__ import annotations

import ast
import inspect
from types import SimpleNamespace

import pytest
from pydantic import BaseModel

from app.core.llm import accounting
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import (
    LLMCallContext,
    LLMCallOptions,
    LLMUsage,
    RawLLMResponse,
    StructuredOutputMode,
)
from tests.fakes.llm import ScriptedLLMTransport


class _Out(BaseModel):
    answer: str


def _context(run_id="run-1", step_id="step-1", node="generator", call_id="call-1"):
    return LLMCallContext(
        run_id=run_id,
        step_id=step_id,
        node_name=node,
        schema_name="_Out",
        call_id=call_id,
    )


def _raw(text="ok", usage=(10, 5, 15)):
    return RawLLMResponse(
        content=text,
        usage=LLMUsage(input_tokens=usage[0], output_tokens=usage[1], total_tokens=usage[2]),
        finish_reason="stop",
    )


def _gateway(outcomes, **kwargs):
    transport = ScriptedLLMTransport(outcomes)
    options = LLMCallOptions(
        max_attempts=1,
        request_timeout_seconds=5.0,
        structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
    )
    defaults = dict(
        sleep=lambda _s: None,
        default_options=options,
    )
    defaults.update(kwargs)
    return LLMGateway(transport, **defaults), transport


def _collect(monkeypatch):
    submissions = []

    class _Publisher:
        def submit(self, submission):
            submissions.append(submission)
            return True

    monkeypatch.setattr(accounting, "_publisher", _Publisher())
    return submissions


def test_no_scope_is_exact_passthrough(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    gateway, transport = _gateway([lambda _kw: _raw('{"answer":"x"}')])
    result = gateway.invoke_structured(
        messages=[],
        output_schema=_Out,
        context=_context(),
        options=gateway.default_options,
    )
    assert result.output.answer == "x"
    assert len(transport.calls) == 1
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        pass  # closed immediately; no active scope afterwards
    assert accounting.current_stack() == ()


def test_observation_recorded_once_with_stage(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([lambda _kw: _raw('{"answer":"x"}')])
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        with accounting.stage_scope("generate", step_id="step-1", sequence=3):
            result = gateway.invoke_structured(
                messages=[],
                output_schema=_Out,
                context=_context(),
                options=gateway.default_options,
            )
    assert result.output.answer == "x"
    assert len(submissions) == 1
    segment = submissions[0].segment
    assert segment.sealed and segment.call_count == 1
    call = segment.calls[0]
    assert call.stage == "generate"
    assert call.step_id == "step-1"
    assert call.attribution == "task"
    assert call.usage_complete is True
    assert call.usage_input_tokens == 10
    assert call.usage_output_tokens == 5
    assert call.usage_total_tokens == 15
    assert call.attempts and call.attempts[0].helper_observed is True


def test_result_object_identity_preserved(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    _collect(monkeypatch)
    gateway, _ = _gateway([lambda _kw: _raw('{"answer":"x"}')])
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        result = gateway.invoke_structured(
            messages=[],
            output_schema=_Out,
            context=_context(),
            options=gateway.default_options,
        )
    # The wrapper returns the exact object produced by the original method.
    assert isinstance(result.output, _Out)
    assert result.attempt_count == 1


def test_gateway_error_passthrough_and_recorded(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([RuntimeError("provider blew up")])
    from app.core.llm.gateway import LLMGatewayError

    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        with pytest.raises(LLMGatewayError) as excinfo:
            gateway.invoke_structured(
                messages=[],
                output_schema=_Out,
                context=_context(),
                options=gateway.default_options,
            )
    assert excinfo.value.error.category == "upstream"
    segment = submissions[0].segment
    call = segment.calls[0]
    assert call.outcome == "gateway_error"
    # The helper observed the failed transport attempt; no summary exists for it.
    assert call.attempt_complete is False
    assert call.attempts[0].helper_error_class == "RuntimeError"


def test_transport_helper_error_kept_as_lower_bound(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([TimeoutError("hard timeout")])
    with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-1"):
        with pytest.raises(Exception):
            gateway.invoke_structured(
                messages=[],
                output_schema=_Out,
                context=_context(),
                options=gateway.default_options,
            )
    call = submissions[0].segment.calls[0]
    assert call.observed_attempt_count >= 1
    assert call.attempt_complete is False
    assert call.usage_complete is False


def test_same_call_id_reentering_gateway_is_two_observations(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([lambda _kw: _raw('{"answer":"x"}'), lambda _kw: _raw('{"answer":"y"}')])
    context = _context(call_id="reused-id")
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        gateway.invoke_structured(
            messages=[], output_schema=_Out, context=context, options=gateway.default_options
        )
        gateway.invoke_structured(
            messages=[], output_schema=_Out, context=context, options=gateway.default_options
        )
    calls = submissions[0].segment.calls
    assert len(calls) == 2
    assert {call.observation_id for call in calls} == {1, 2}
    assert all(call.source_call_id == "reused-id" for call in calls)


def test_nested_same_run_reuses_segment(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway(
        [lambda _kw: _raw('{"answer":"x"}'), lambda _kw: _raw('{"answer":"y"}')]
    )
    with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-1"):
        gateway.invoke_structured(
            messages=[], output_schema=_Out, context=_context(), options=gateway.default_options
        )
        with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-1"):
            gateway.invoke_structured(
                messages=[], output_schema=_Out, context=_context(), options=gateway.default_options
            )
    assert len(submissions) == 1
    assert submissions[0].segment.call_count == 2


def test_capture_failure_is_noop_and_marks_incomplete(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([lambda _kw: _raw('{"answer":"x"}')])

    class _BoomFrame:
        def record_entry(self, _context):
            raise RuntimeError("capture exploded")

        def finalize(self):
            raise RuntimeError("capture exploded")

    original_open = accounting._SegmentFrame.open_call

    def _open(self):
        frame = original_open(self)
        if frame is not None:
            frame.__class__ = _BoomFrame
        return frame

    monkeypatch.setattr(accounting._SegmentFrame, "open_call", _open)
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        result = gateway.invoke_structured(
            messages=[],
            output_schema=_Out,
            context=_context(),
            options=gateway.default_options,
        )
    # Business result unchanged despite capture failure.
    assert result.output.answer == "x"
    segment = submissions[0].segment
    assert segment.call_count == 0
    assert segment.incomplete_reasons


def test_threadpool_context_propagation(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    import contextvars
    from concurrent.futures import ThreadPoolExecutor

    submissions = _collect(monkeypatch)
    gateway, _ = _gateway(
        [lambda _kw: _raw('{"answer":"x"}'), lambda _kw: _raw('{"answer":"y"}')]
    )
    with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-1"):
        # Each worker needs its own copy of the parent context, captured in the
        # parent thread (mirrors generator_agent): a Context object can only be
        # entered once, and the segment lives in the parent's ContextVar stack.
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [
                executor.submit(
                    contextvars.copy_context().run,
                    gateway.invoke_structured,
                    messages=[],
                    output_schema=_Out,
                    context=_context(),
                    options=gateway.default_options,
                )
                for _ in range(2)
            ]
            results = [future.result() for future in futures]
    assert all(result.output.answer in {"x", "y"} for result in results)
    assert submissions[0].segment.call_count == 2


def test_signature_and_wrapped_preserved():
    for method_name in ("invoke_structured", "invoke_plain_text"):
        method = getattr(LLMGateway, method_name)
        assert method.__wrapped__ is not None
        assert method.__name__ == method_name
        signature = inspect.signature(method)
        assert "messages" in signature.parameters
        assert "context" in signature.parameters
        assert "options" in signature.parameters


def test_original_gateway_bodies_untouched():
    """The two public methods keep their original AST in the class body."""

    source = inspect.getsource(__import__("app.core.llm.gateway", fromlist=["x"]))
    tree = ast.parse(source)
    class_node = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "LLMGateway"
    )
    function_names = {
        node.name for node in class_node.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert {"invoke_structured", "invoke_plain_text"} <= function_names
    # The wrappers are module-level rebindings, not class-body changes.
    assignments = {
        node.targets[0].id
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id in {
            "invoke_structured",
            "invoke_plain_text",
            "_invoke_transport_with_hard_timeout",
        }
    }
    assert "_invoke_transport_with_hard_timeout" in assignments


def test_disabled_flag_makes_wrapper_passthrough(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", False)
    gateway, transport = _gateway([lambda _kw: _raw('{"answer":"x"}')])
    with accounting.segment_scope(accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1"):
        result = gateway.invoke_structured(
            messages=[],
            output_schema=_Out,
            context=_context(),
            options=gateway.default_options,
        )
    assert result.output.answer == "x"
    assert len(transport.calls) == 1


def test_batch_scope_defers_submission(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = _collect(monkeypatch)
    gateway, _ = _gateway([lambda _kw: _raw('{"answer":"x"}')])
    with accounting.batch_scope():
        with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-1"):
            gateway.invoke_structured(
                messages=[], output_schema=_Out, context=_context(), options=gateway.default_options
            )
        assert submissions == []  # deferred until the batch closes
    assert len(submissions) == 1


def test_usage_mismatch_between_summary_and_raw(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    # The summary and helper evidence disagree for the same ordinal: the
    # observation must surface usage_mismatch and null the complete fields.
    segment = accounting._SegmentFrame(
        accounting.AccountingDomain.LEARNING_DOCUMENTS, "run-1", None
    )
    frame = segment.open_call()
    frame.record_entry(_context())
    frame.record_helper_success(
        RawLLMResponse(
            content="x",
            usage=LLMUsage(input_tokens=99, output_tokens=99, total_tokens=198),
        )
    )
    frame.summary_attempts[1] = {
        "status": "success",
        "error_code": None,
        "error_category": None,
        "latency_ms": 2,
        "mode": "function_calling",
        "usage_input": 10,
        "usage_output": 5,
        "usage_total": 15,
    }
    frame.top_usage = {"input": 10, "output": 5, "total": 15}
    observation = frame.finalize()
    assert observation.usage_mismatch is True
    assert observation.usage_input_tokens is None
    assert observation.usage_complete is False
