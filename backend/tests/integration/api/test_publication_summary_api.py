"""The derived publication summary is identical across every text query entry."""

from __future__ import annotations

import json
from types import SimpleNamespace

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from app.api.generation import generation as generate
from app.api.runs import run_queries as runs
from app.core.security.errors import ApplicationError
from app.db.audit.memory import MemoryAuditRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.learning_documents.schemas import (
    GenerateRequest,
    GenerationJobStatusResponse,
    LearnerProfile,
    LearningResource,
)
from app.models.shared.persistence import CreateRunCommand, RunSummary, canonical_hash
from app.services.generation.jobs import GenerationJobService
from app.services.runs.queries import RunQueryService

RUN_ID = "run-pub"
LEARNER_ID = "learner-pub"
REQUEST_TYPES = ["讲义", "实操指南", "分阶测试题"]


def _seed(repositories) -> None:
    audit_repo, job_repo, resource_repo, _ = repositories
    snapshot = {"learner_id": LEARNER_ID, "topic": "T47", "resource_types": REQUEST_TYPES}
    audit_repo.create_run(CreateRunCommand(
        run_id=RUN_ID,
        learner_id=LEARNER_ID,
        knowledge_base_id=None,
        topic="T47",
        request_snapshot=snapshot,
        request_hash=canonical_hash(snapshot),
    ))
    job_repo.create(
        run_id=RUN_ID,
        learner_id=LEARNER_ID,
        topic="T47",
        knowledge_base_id=None,
        request_payload=GenerateRequest(
            learner_id=LEARNER_ID, topic="T47", resource_types=REQUEST_TYPES
        ).model_dump(mode="json"),
    )
    for order, (spec_id, resource_type) in enumerate(
        (("spec-video", "讲义"), ("spec-practice", "实操指南"), ("spec-assessment", "分阶测试题"))
    ):
        resource_repo.save_spec(ResourceSpecRecord(
            resource_spec_id=spec_id,
            run_id=RUN_ID,
            resource_type=resource_type,
            learning_objective=f"覆盖 {resource_type}",
            difficulty="初级",
            representations=[{"representation": "text"}],
            display_order=order,
        ))
    for spec_id, resource_type, resource_id, state in (
        ("spec-video", "讲义", "res-video", "approved"),
        ("spec-practice", "实操指南", "res-practice", "approved"),
        ("spec-assessment", "分阶测试题", None, "failed"),
    ):
        resource_repo.upsert_execution(ResourceExecutionRecord(
            run_id=RUN_ID,
            resource_spec_id=spec_id,
            resource_type=resource_type,
            state=state,
            resource_id=resource_id,
            attempt=1,
            agent_name="TextResourceAgent",
            prompt_version="v1",
            artifact_format="markdown",
        ))
    for resource_id, resource_type, spec_id in (
        ("res-video", "讲义", "spec-video"),
        ("res-practice", "实操指南", "spec-practice"),
    ):
        resource_repo.save(
            LearningResource(
                resource_id=resource_id,
                resource_type=resource_type,
                difficulty="初级",
                knowledge_points=["kp-1"],
                source_refs=[],
                run_id=RUN_ID,
                resource_spec_id=spec_id,
                publication_status="published",
            ),
            learner_id=LEARNER_ID,
            topic="T47",
        )


def _app(*, current_user=None):
    audit_repo = MemoryAuditRepository()
    job_repo = MemoryGenerationJobRepository()
    resource_repo = MemoryResourceRepository()
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id=LEARNER_ID,
        learner_type="测试",
        education="本科",
        major="软件工程",
        learning_goal="验证发布汇总",
    ))
    repositories = (audit_repo, job_repo, resource_repo, learner_repo)
    _seed(repositories)

    generation_service = SimpleNamespace(resource_repo=resource_repo)
    job_service = GenerationJobService(job_repo, generation_service)
    run_service = RunQueryService(
        audit_repo,
        resource_repo,
        generation_job_repository=job_repo,
    )

    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: SimpleNamespace(get=learner_repo.get),
        generation_job_service=lambda: job_service,
        run_query_service=lambda: run_service,
    )

    if current_user is not None:
        @app.middleware("http")
        async def inject_user(request: Request, call_next):
            request.state.current_user = current_user
            return await call_next(request)

    @app.exception_handler(ApplicationError)
    async def handle_application_error(request: Request, exc: ApplicationError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code.value, "message": exc.public_message},
        )

    app.include_router(generate.router, prefix="/api/generate")
    app.include_router(runs.router, prefix="/api/runs")
    return TestClient(app), repositories


def test_job_and_run_endpoints_agree_on_the_same_publication_summary():
    client, _ = _app()

    job = client.get(f"/api/generate/jobs/{RUN_ID}")
    assert job.status_code == 200
    summary = job.json()["publish_summary"]
    assert summary["total"] == 3
    assert summary["published"] == 2
    assert summary["unpublished"] == 1
    assert summary["pending_review"] == 0
    assert summary["completeness"] == "complete"
    assert summary["incomplete_reasons"] == []

    listing = client.get("/api/generate/jobs", params={"learner_id": LEARNER_ID})
    assert listing.status_code == 200
    assert listing.json()["items"][0]["publish_summary"] == summary

    run = client.get(f"/api/runs/{RUN_ID}")
    assert run.status_code == 200
    assert run.json()["publish_summary"] == summary

    timeline = client.get(f"/api/runs/{RUN_ID}/timeline", params={"limit": 100})
    assert timeline.status_code == 200
    assert timeline.json()["run"]["publish_summary"] == summary
    assert "publish_summary" not in timeline.json()


def test_existing_progress_field_keeps_its_meaning():
    client, _ = _app()
    body = client.get(f"/api/generate/jobs/{RUN_ID}").json()
    progress = body["resource_progress_summary"]
    assert progress["total"] == 3
    assert progress["published"] == 2
    assert progress["failed"] == 1
    assert body["publish_summary"]["total"] == 3


def test_missing_job_reports_request_missing_instead_of_full_success():
    _, repositories = _app()
    audit_repo, job_repo, resource_repo, _ = repositories
    job_repo._store.pop(RUN_ID, None)  # noqa: SLF001 - drop the job to model a legacy run
    run_service = RunQueryService(audit_repo, resource_repo, generation_job_repository=job_repo)
    body = run_service.get_summary(RUN_ID)
    assert body.publish_summary is not None
    assert body.publish_summary.total is None
    assert body.publish_summary.published == 2
    assert body.publish_summary.completeness.value == "partial"
    assert [reason.value for reason in body.publish_summary.incomplete_reasons] == ["request_missing"]
    assert resource_repo.list_specs_by_run(RUN_ID)


def test_errors_and_pagination_contracts_are_unchanged():
    client, _ = _app()
    assert client.get("/api/runs/missing").status_code == 404
    assert client.get("/api/runs/missing").json()["code"] == "WORKFLOW_RUN_NOT_FOUND"
    assert client.get(f"/api/runs/{RUN_ID}/timeline", params={"limit": 501}).status_code == 422
    assert client.get("/api/generate/jobs/missing").status_code == 404
    assert client.get("/api/generate/jobs", params={"learner_id": "missing"}).status_code == 404


def test_invisible_profile_still_returns_404():
    client, _ = _app(current_user=SimpleNamespace(user_id="another-user"))
    assert client.get("/api/generate/jobs", params={"learner_id": LEARNER_ID}).status_code == 404
    client_own = _app(current_user=SimpleNamespace(user_id=None))[0]
    assert client_own.get(f"/api/runs/{RUN_ID}").status_code == 200


def test_legacy_payloads_without_the_field_stay_valid():
    legacy_job = GenerationJobStatusResponse.model_validate(json.loads(json.dumps({
        "run_id": RUN_ID,
        "learner_id": LEARNER_ID,
        "topic": "T47",
        "job_status": "completed",
    })))
    assert legacy_job.publish_summary is None
    assert legacy_job.resource_progress_summary.total == 0

    summary = RunSummary.model_validate({
        "run_id": RUN_ID,
        "status": "completed",
        "updated_at": "2026-11-07T09:30:00Z",
        "replay_completeness": "complete",
    })
    assert summary.publish_summary is None


def test_run_summary_from_record_leaves_the_derived_field_empty():
    _, repositories = _app()
    audit_repo = repositories[0]
    record = audit_repo.get_run(RUN_ID)
    summary = RunSummary.from_record(record)
    assert summary.publish_summary is None
    assert summary.run_id == RUN_ID
