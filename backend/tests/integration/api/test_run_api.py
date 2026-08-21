from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api import runs
from app.core.errors import ApplicationError
from app.services.run_query_service import RunQueryService
from backend.tests.fakes.persistence import create_command, memory_repository


def _client():
    repository = memory_repository()
    command = create_command("run-api")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    app = FastAPI()
    app.container = SimpleNamespace(run_query_service=lambda: RunQueryService(repository))

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code.value, "message": exc.public_message},
        )

    app.include_router(runs.router, prefix="/api/runs")
    return TestClient(app), command.run_id


def test_run_summary_and_paginated_timeline_are_queryable():
    client, run_id = _client()
    summary = client.get(f"/api/runs/{run_id}")
    assert summary.status_code == 200
    assert summary.json()["run_id"] == run_id
    assert "owner_instance_id" not in summary.json()
    assert "request_hash" not in summary.json()
    timeline = client.get(f"/api/runs/{run_id}/timeline", params={"limit": 1})
    assert timeline.status_code == 200
    assert len(timeline.json()["events"]) == 1
    assert timeline.json()["next_event_sequence"] == 1


def test_run_api_returns_stable_404_and_validates_limit():
    client, run_id = _client()
    missing = client.get("/api/runs/missing")
    assert missing.status_code == 404
    assert missing.json()["code"] == "WORKFLOW_RUN_NOT_FOUND"
    assert client.get(f"/api/runs/{run_id}/timeline", params={"limit": 501}).status_code == 422
