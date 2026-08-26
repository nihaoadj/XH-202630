import asyncio
import json
from datetime import datetime, timezone
from functools import wraps
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from app.api.runs import run_queries as runs
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.models.shared.persistence import ReplayCompleteness, RunStatus, WorkflowEventType
from app.services.runs.events import RunEventStreamService, to_public_event
from app.services.runs.queries import RunQueryService
from backend.tests.fakes.persistence import create_command, memory_repository, sqlite_repository


def async_test(function):
    @wraps(function)
    def run(*args, **kwargs):
        return asyncio.run(function(*args, **kwargs))

    return run


def _settings(*, page_size=100, poll=0.001, heartbeat=0.003):
    return SimpleNamespace(
        workflow_sse_event_page_size=page_size,
        workflow_sse_poll_interval_seconds=poll,
        workflow_sse_heartbeat_seconds=heartbeat,
    )


def _job(repo, run_id):
    repo.create(run_id, "learner-001", "RAG", "kb-001", {"learner_id": "learner-001"})


def _running_repository(run_id="stream-run"):
    repository = memory_repository()
    command = create_command(run_id)
    repository.create_run(command)
    repository.start_run(run_id, occurred_at=command.occurred_at)
    return repository


def _append(repository, run_id, count):
    for index in range(count):
        repository.append_event(
            run_id,
            WorkflowEventType.CHECKPOINT_SAVED,
            payload={"count": index},
            occurred_at=datetime.now(timezone.utc),
            event_id=f"evt-{run_id}-{index}",
        )


def _data(frame):
    line = next(item for item in frame.splitlines() if item.startswith("data: "))
    return json.loads(line.removeprefix("data: "))


async def _take(generator, count):
    items = []
    try:
        for _ in range(count):
            items.append(await asyncio.wait_for(anext(generator), timeout=1))
    finally:
        await generator.aclose()
    return items


def test_queued_job_snapshot_precedes_agent_run_and_missing_is_404():
    jobs = MemoryGenerationJobRepository()
    _job(jobs, "queued-run")
    service = RunEventStreamService(memory_repository(), jobs, _settings())
    snapshot = service.get_snapshot("queued-run")
    assert snapshot.job_status == "queued"
    assert snapshot.run_status is None
    assert snapshot.last_event_sequence == 0
    with pytest.raises(ApplicationError) as exc:
        service.get_snapshot("missing")
    assert exc.value.code == ErrorCode.WORKFLOW_STREAM_RUN_NOT_FOUND


def test_job_snapshot_is_best_effort_when_agent_run_exists():
    repository = _running_repository()
    jobs = MemoryGenerationJobRepository()

    def unavailable(_):
        raise RuntimeError("private database detail")

    jobs.get = unavailable
    service = RunEventStreamService(repository, jobs, _settings())
    assert service.get_snapshot("stream-run").run_status == "running"
    with pytest.raises(ApplicationError) as exc:
        service.get_snapshot("missing")
    assert exc.value.code == ErrorCode.WORKFLOW_STREAM_UNAVAILABLE


def test_cursor_contract_prefers_last_event_id_and_rejects_invalid_values():
    assert RunEventStreamService.resolve_cursor(None, None) == 0
    assert RunEventStreamService.resolve_cursor("2", None) == 2
    assert RunEventStreamService.resolve_cursor("2", "2") == 2
    assert RunEventStreamService.resolve_cursor("2", "3") == 2
    for header, query in (("x", None), (None, "-1")):
        with pytest.raises(ApplicationError) as exc:
            RunEventStreamService.resolve_cursor(header, query)
        assert exc.value.code == ErrorCode.WORKFLOW_STREAM_CURSOR_INVALID


@async_test
async def test_replay_order_after_sequence_reconnect_and_multiple_clients():
    repository = _running_repository()
    _append(repository, "stream-run", 3)
    jobs = MemoryGenerationJobRepository()
    _job(jobs, "stream-run")
    service = RunEventStreamService(repository, jobs, _settings())
    snapshot = service.get_snapshot("stream-run")

    first = service.stream("stream-run", cursor=2, initial_snapshot=snapshot)
    frames = await _take(first, 4)
    assert frames[0].startswith("event: snapshot")
    assert [_data(item)["sequence"] for item in frames[1:]] == [3, 4, 5]

    repository.append_event(
        "stream-run",
        WorkflowEventType.REVISION_REQUESTED,
        payload={"revision_count": 1},
        occurred_at=datetime.now(timezone.utc),
    )
    reconnected_a = service.stream("stream-run", cursor=5, initial_snapshot=service.get_snapshot("stream-run"))
    reconnected_b = service.stream("stream-run", cursor=5, initial_snapshot=service.get_snapshot("stream-run"))
    frames_a, frames_b = await asyncio.gather(_take(reconnected_a, 2), _take(reconnected_b, 2))
    assert _data(frames_a[1])["sequence"] == 6
    assert _data(frames_b[1])["sequence"] == 6


@async_test
async def test_heartbeat_does_not_advance_cursor_or_persist_event():
    jobs = MemoryGenerationJobRepository()
    _job(jobs, "queued-run")
    repository = memory_repository()
    service = RunEventStreamService(repository, jobs, _settings())
    generator = service.stream("queued-run", cursor=0, initial_snapshot=service.get_snapshot("queued-run"))
    frames = await _take(generator, 2)
    assert frames[1].startswith("event: ping")
    assert _data(frames[1])["last_event_sequence"] == 0
    assert repository.get_run("queued-run") is None


@async_test
async def test_terminal_closes_after_backlog_and_disconnect_is_read_only():
    repository = _running_repository()
    jobs = MemoryGenerationJobRepository()
    _job(jobs, "stream-run")
    jobs.mark_running("stream-run")
    repository.fail_run(
        "stream-run",
        error_code="TEST_FAILURE",
        occurred_at=datetime.now(timezone.utc),
    )
    jobs.mark_failed("stream-run", "sanitized")
    service = RunEventStreamService(repository, jobs, _settings(page_size=2))
    frames = [item async for item in service.stream(
        "stream-run",
        cursor=0,
        initial_snapshot=service.get_snapshot("stream-run"),
    )]
    sequences = [_data(item)["sequence"] for item in frames if item.startswith("id: ")]
    assert sequences == list(range(1, repository.get_run("stream-run").last_event_sequence + 1))

    before = repository.get_run("stream-run")
    disconnected = service.stream(
        "stream-run",
        cursor=before.last_event_sequence,
        initial_snapshot=service.get_snapshot("stream-run"),
        is_disconnected=lambda: asyncio.sleep(0, result=True),
    )
    assert (await anext(disconnected)).startswith("event: snapshot")
    with pytest.raises(StopAsyncIteration):
        await anext(disconnected)
    assert repository.get_run("stream-run") == before

    active = _running_repository("disconnect-run")
    active_jobs = MemoryGenerationJobRepository()
    _job(active_jobs, "disconnect-run")
    active_jobs.mark_running("disconnect-run")
    active_service = RunEventStreamService(active, active_jobs, _settings())
    watcher = active_service.stream(
        "disconnect-run",
        cursor=active.get_run("disconnect-run").last_event_sequence,
        initial_snapshot=active_service.get_snapshot("disconnect-run"),
        is_disconnected=lambda: asyncio.sleep(0, result=True),
    )
    await anext(watcher)
    with pytest.raises(StopAsyncIteration):
        await anext(watcher)
    now = datetime.now(timezone.utc)
    active.mark_finalizing(
        "disconnect-run",
        workflow_status="completed",
        current_node="supervisor",
        generation_attempt=1,
        revision_count=0,
        retrieval_status="ready",
        final_decision="completed",
        occurred_at=now,
    )
    active.complete_run(
        "disconnect-run",
        status=RunStatus.COMPLETED,
        workflow_status="completed",
        execution_status="success",
        final_decision="completed",
        occurred_at=now,
    )
    active_jobs.mark_completed("disconnect-run", [])
    assert active.get_run("disconnect-run").status == RunStatus.COMPLETED
    assert active_jobs.get("disconnect-run").job_status == "completed"


@async_test
async def test_sequence_gap_fails_closed_but_legacy_partial_does_not_invent_events():
    repository = _running_repository()
    repository.fail_run("stream-run", error_code="TEST", occurred_at=datetime.now(timezone.utc))
    del repository.events["stream-run"][1]
    jobs = MemoryGenerationJobRepository()
    service = RunEventStreamService(repository, jobs, _settings())
    frames = [item async for item in service.stream(
        "stream-run", cursor=0, initial_snapshot=service.get_snapshot("stream-run")
    )]
    assert frames[-1].startswith("event: stream_error")
    assert _data(frames[-1])["code"] == "WORKFLOW_STREAM_EVENT_SEQUENCE_INVALID"

    repository.runs["stream-run"]["replay_completeness"] = ReplayCompleteness.LEGACY_PARTIAL.value
    frames = [item async for item in service.stream(
        "stream-run", cursor=0, initial_snapshot=service.get_snapshot("stream-run")
    )]
    assert all("stream_error" not in item for item in frames)
    assert [_data(item)["sequence"] for item in frames[1:]] == [1, 3]


def test_public_mapper_is_allow_listed_and_bounded():
    repository = _running_repository()
    event = repository.append_event(
        "stream-run",
        WorkflowEventType.CLAIM_JUDGEMENT_COMPLETED,
        payload={
            "claim_ids": [f"claim-{index}" for index in range(150)],
            "absolute_path": "D:/private/file.txt",
            "model_internal": "hidden",
        },
        occurred_at=datetime.now(timezone.utc),
    )
    # Simulate a legacy row with nested counters; the public projection remains
    # bounded even when reading records created before the strict scalar contract.
    event = event.model_copy(update={"payload": {
        **event.payload,
        "verdict_counts": {"supported": 2, "contradicted": 1},
    }})
    public = to_public_event(event)
    assert len(public.payload["claim_ids"]) == 100
    assert public.payload["supported_count"] == 2
    assert "absolute_path" not in public.payload
    assert "model_internal" not in public.payload
    with pytest.raises(ValueError):
        repository.append_event(
            "stream-run",
            WorkflowEventType.CHECKPOINT_SAVED,
            payload={"api_key": "must-not-stream"},
            occurred_at=datetime.now(timezone.utc),
        )


@async_test
async def test_sqlite_cross_service_replay_uses_database_not_listener(tmp_path):
    repository, _ = sqlite_repository(tmp_path)
    factory = repository.session_factory
    jobs = SQLGenerationJobRepository(factory)
    command = create_command("sqlite-stream")
    _job(jobs, command.run_id)
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    _append(repository, command.run_id, 2)

    fresh_repository = SQLAuditRepository(factory)
    fresh_jobs = SQLGenerationJobRepository(factory)
    service = RunEventStreamService(fresh_repository, fresh_jobs, _settings())
    generator = service.stream(
        command.run_id,
        cursor=2,
        initial_snapshot=service.get_snapshot(command.run_id),
    )
    frames = await _take(generator, 3)
    assert [_data(item)["sequence"] for item in frames[1:]] == [3, 4]


@pytest.mark.parametrize("event_count", [100, 500])
@async_test
async def test_backlog_over_page_size_drains_without_heartbeat(event_count):
    repository = _running_repository("large-run")
    _append(repository, "large-run", event_count)
    repository.fail_run("large-run", error_code="TEST", occurred_at=datetime.now(timezone.utc))
    jobs = MemoryGenerationJobRepository()
    service = RunEventStreamService(repository, jobs, _settings(page_size=100))
    frames = [item async for item in service.stream(
        "large-run", cursor=0, initial_snapshot=service.get_snapshot("large-run")
    )]
    event_frames = [item for item in frames if item.startswith("id: ")]
    assert len(event_frames) == repository.get_run("large-run").last_event_sequence
    assert not any(item.startswith("event: ping") for item in frames)
    assert sum(len(item.encode("utf-8")) for item in frames) < len(frames) * 2048


def test_sse_endpoint_headers_last_event_id_priority_and_terminal_response():
    repository = _running_repository("api-stream")
    repository.fail_run("api-stream", error_code="TEST", occurred_at=datetime.now(timezone.utc))
    jobs = MemoryGenerationJobRepository()
    service = RunEventStreamService(repository, jobs, _settings())
    app = FastAPI()
    app.container = SimpleNamespace(
        run_query_service=lambda: RunQueryService(repository),
        run_event_stream_service=lambda: service,
    )

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError):
        return JSONResponse(status_code=exc.status_code, content={"code": exc.code.value})

    app.include_router(runs.router, prefix="/api/runs")
    client = TestClient(app)
    response = client.get("/api/runs/api-stream/events", headers={"Last-Event-ID": "2"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    assert "event: snapshot" in response.text
    assert "id: 3" in response.text
    priority = client.get(
        "/api/runs/api-stream/events?after_sequence=1",
        headers={"Last-Event-ID": "2"},
    )
    assert priority.status_code == 200
    assert "id: 3" in priority.text
