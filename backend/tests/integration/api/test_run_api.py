from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.runs import run_queries as runs
from app.core.security.errors import ApplicationError
from app.services.runs.queries import RunQueryService
from app.db.claim.memory import MemoryClaimRepository
from app.models.shared.persistence import canonical_hash
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


def test_claim_endpoint_reports_started_but_failed_audit_without_claim_rows():
    repository = memory_repository()
    command = create_command("run-claim-failed")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    projection = {
        "run_id": command.run_id,
        "include_claim_check": True,
        "claim_check_status": "failed",
        "claim_failed_resource_ids": ["resource-1"],
        "claim_metrics": {},
        "assessment_claim_skipped_resource_ids": [],
    }
    repository.save_checkpoint(
        run_id=command.run_id,
        step_id="claim-extract",
        step_sequence=1,
        node_name="claim_extractor",
        state_projection=projection,
        state_hash=canonical_hash(projection),
        occurred_at=datetime.now(timezone.utc),
    )

    response = RunQueryService(
        repository,
        claim_repository=MemoryClaimRepository(),
    ).get_claims(command.run_id)

    assert response.audit_status.value == "incomplete"
    assert response.resource_metrics["resource-1"].metric_status.value == "incomplete"


def test_claim_endpoint_reports_structured_assessment_skip_without_claim_rows():
    repository = memory_repository()
    command = create_command("run-claim-assessment")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    projection = {
        "run_id": command.run_id,
        "include_claim_check": True,
        "claim_check_status": "completed",
        "claim_failed_resource_ids": [],
        "claim_metrics": {
            "assessment-1": {
                "metric_status": "not_applicable",
                "claim_hallucination_rate": None,
                "claim_total": 0,
                "factual_claim_total": 0,
                "supported_claim_total": 0,
                "contradicted_claim_total": 0,
                "not_in_evidence_claim_total": 0,
                "non_factual_claim_total": 0,
                "incomplete_claim_total": 0,
                "audit_mode": "structured_assessment_internal",
            },
        },
        "assessment_claim_skipped_resource_ids": ["assessment-1"],
    }
    repository.save_checkpoint(
        run_id=command.run_id,
        step_id="claim-judge",
        step_sequence=1,
        node_name="claim_judge",
        state_projection=projection,
        state_hash=canonical_hash(projection),
        occurred_at=datetime.now(timezone.utc),
    )

    response = RunQueryService(
        repository,
        claim_repository=MemoryClaimRepository(),
    ).get_claims(command.run_id)

    assert response.audit_status.value == "not_applicable"
    assert response.resource_metrics["assessment-1"].metric_status.value == "not_applicable"
