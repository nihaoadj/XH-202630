"""Fault isolation and non-blocking behaviour of the accounting runtime."""

from __future__ import annotations

import shutil
import tempfile
import time
from pathlib import Path

import pytest

from app.core.llm import accounting
from app.models.shared.llm_accounting import SegmentSubmissionV1, AccountingSegmentV1
from app.services.runs import llm_accounting_runtime as runtime
from tests.fakes.llm import ScriptedLLMTransport
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import LLMCallOptions, LLMCallContext, StructuredOutputMode
from pydantic import BaseModel


class _Out(BaseModel):
    answer: str


def _observation_segment(run_id="run-iso", calls=1) -> AccountingSegmentV1:
    from app.models.shared.llm_accounting import LLMCallObservationV1

    return AccountingSegmentV1(
        domain="courseware",
        run_id=run_id,
        segment_id="seg-iso",
        process_nonce="proc-iso",
        calls=[
            LLMCallObservationV1(
                domain="courseware",
                run_id=run_id,
                segment_id="seg-iso",
                observation_id=index + 1,
                stage="composing",
            )
            for index in range(calls)
        ],
        call_count=calls,
        sealed=True,
    )


@pytest.fixture()
def enabled(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    monkeypatch.setattr(accounting, "_publisher", None)
    yield
    runtime.stop_llm_accounting_runtime()


def test_full_queue_refuses_without_blocking(enabled, monkeypatch):
    import queue as _queue

    full_queue = _queue.Queue(maxsize=1)
    full_queue.put({"kind": "filler"})

    class _FakeQueue:
        def qsize(self):
            return 1

        def put_nowait(self, item):
            raise _queue.Full(item)

    credit = _queue.Queue()
    publisher = runtime._QueuePublisher(_FakeQueue(), credit)
    submission = SegmentSubmissionV1(
        segment=_observation_segment(),
        payload_hash="deadbeef",
    )
    started = time.perf_counter()
    accepted = publisher.submit(submission)
    elapsed = time.perf_counter() - started
    assert accepted is False
    assert elapsed < 1.0


def test_publisher_exception_never_reaches_business(enabled, monkeypatch):
    class _ExplodingPublisher:
        def submit(self, submission):
            raise RuntimeError("publisher exploded")

    monkeypatch.setattr(accounting, "_publisher", _ExplodingPublisher())
    transport = ScriptedLLMTransport(
        [_raw_for_structured()],
    )
    gateway = LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )
    with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-iso"):
        result = gateway.invoke_structured(
            messages=[],
            output_schema=_Out,
            context=_context(),
            options=gateway.default_options,
        )
    assert result.output.answer == "x"


def _raw_for_structured():
    from app.models.shared.llm import LLMUsage, RawLLMResponse

    return RawLLMResponse(
        content='{"answer":"x"}',
        usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        finish_reason="stop",
    )


def _context():
    return LLMCallContext(
        run_id="run-iso", step_id="step-iso", node_name="scene", schema_name="_Out"
    )


def test_writer_subprocess_persists_segment(tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    assert rt.start() is True
    try:
        submission = SegmentSubmissionV1(
            segment=_observation_segment(run_id="run-iso-proc"),
            payload_hash=_hash(_observation_segment(run_id="run-iso-proc")),
        )
        assert accounting._publisher is not None
        accepted = accounting._publisher.submit(submission)
        assert accepted is True
        deadline = time.monotonic() + 30
        from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

        repository = SQLLLMAccountingRepository(str(db_path))
        persisted = []
        while time.monotonic() < deadline:
            records = repository.get_task("courseware", "run-iso-proc")
            if records.calls:
                persisted = records.calls
                break
            time.sleep(0.2)
        repository.close()
        assert persisted, "writer child must persist the submitted segment"
    finally:
        stop_started = time.perf_counter()
        rt.stop()
        assert time.perf_counter() - stop_started < 5.0


def _hash(segment: AccountingSegmentV1) -> str:
    from app.models.shared.llm_accounting import canonical_accounting_hash

    return canonical_accounting_hash(segment.stable_payload())


def test_runtime_stop_terminates_promptly(tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-stop.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    rt.start()
    stop_started = time.perf_counter()
    rt.stop()
    elapsed = time.perf_counter() - stop_started
    assert elapsed < 5.0
    assert rt.started is False


def test_business_gateway_unaffected_while_writer_dead(enabled, tmp_dir_session):
    db_path = Path(tmp_dir_session) / "accounting-dead.db"
    rt = runtime.LLMAccountingRuntime(db_path)
    rt.start()
    publisher = accounting._publisher
    # Kill the writer child: submissions then fail fast but never block.
    if rt._process is not None:
        rt._process.terminate()
        rt._process.join(timeout=5)
    transport = ScriptedLLMTransport([_raw_for_structured()])
    gateway = LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )
    started = time.perf_counter()
    with accounting.segment_scope(accounting.AccountingDomain.COURSEWARE, "run-iso-dead"):
        result = gateway.invoke_structured(
            messages=[],
            output_schema=_Out,
            context=_context(),
            options=gateway.default_options,
        )
    elapsed = time.perf_counter() - started
    assert result.output.answer == "x"
    assert elapsed < 5.0
    rt.stop()


def test_path_validation_rejects_business_collisions(monkeypatch, tmp_dir_session):
    settings = type("Settings", (), {})()
    settings.database_url = "sqlite:///" + str(Path(tmp_dir_session) / "business.db")
    settings.resources_dir = str(Path(tmp_dir_session) / "resources")
    settings.llm_accounting_db_path = str(Path(tmp_dir_session) / "business.db")
    monkeypatch.setattr(runtime, "get_settings", lambda: settings)
    assert runtime.resolve_llm_accounting_db_path() is None

    inside_resources = str(Path(tmp_dir_session) / "resources" / "accounting.db")
    settings.llm_accounting_db_path = inside_resources
    assert runtime.resolve_llm_accounting_db_path() is None

    settings.llm_accounting_db_path = str(Path(tmp_dir_session) / "accounting.db")
    resolved = runtime.resolve_llm_accounting_db_path()
    assert resolved is not None and resolved.name == "accounting.db"


@pytest.fixture()
def tmp_dir_session():
    tmp = tempfile.mkdtemp()
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)
