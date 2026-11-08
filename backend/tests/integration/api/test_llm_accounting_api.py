"""API contract tests for the two read-only accounting endpoints (T41 §7)."""

from __future__ import annotations

import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.courseware import courseware
from app.api.runs import run_queries
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.learners.repository import create_learner_repository
from app.models.shared.llm_accounting import (
    AccountingSegmentV1,
    LLMCallObservationV1,
    SegmentSubmissionV1,
    canonical_accounting_hash,
)
from app.models.shared.persistence import CreateRunCommand
from app.services.learners.profiles import ProfileService
from app.services.runs.llm_accounting import LLMAccountingQueryService
from app.services.runs.queries import RunQueryService


def _application_error_handler(request: Request, exc: ApplicationError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "code": exc.code.value, "message": exc.public_message, "detail": None},
    )


class _User:
    def __init__(self, user_id):
        self.user_id = user_id


def _build_app(tmp: str, *, current_user=_User("user-1")):
    audit_repo = MemoryAuditRepository()
    run_query_service = RunQueryService(
        repository=audit_repo,
        resource_repository=None,
        claim_repository=None,
        feedback_loop_repository=None,
    )
    learner_repo = create_learner_repository(db_type="memory")
    profile_service = ProfileService(repo=learner_repo)
    db_path = Path(tmp) / "accounting.db"
    accounting_service = LLMAccountingQueryService(str(db_path))

    courseware_service = SimpleNamespace(
        get_job=lambda run_id: None,
    )

    app = FastAPI()
    app.container = SimpleNamespace(
        run_query_service=lambda: run_query_service,
        profile_service=lambda: profile_service,
        llm_accounting_query_service=lambda: accounting_service,
        courseware_service=lambda: courseware_service,
    )
    app.add_exception_handler(ApplicationError, _application_error_handler)

    def _set_user(request: Request):
        if current_user is not None:
            request.state.current_user = current_user

    app.include_router(
        run_queries.router,
        prefix="/api/runs",
        dependencies=[Depends(_set_user)],
    )
    app.include_router(
        courseware.router,
        prefix="/api/resources",
        dependencies=[Depends(_set_user)],
    )
    return app, audit_repo, learner_repo, db_path, courseware_service


def _create_run(audit_repo, run_id="run-api", learner_id="learner-api"):
    now = datetime.now(timezone.utc)
    snapshot = {"synthetic": True}
    from app.models.shared.persistence import canonical_hash

    audit_repo.create_run(
        CreateRunCommand(
            run_id=run_id,
            learner_id=learner_id,
            knowledge_base_id="kb",
            topic="synthetic",
            request_snapshot=snapshot,
            request_hash=canonical_hash(snapshot),
            owner_instance_id="test",
            lease_expires_at=now + timedelta(seconds=60),
            occurred_at=now,
        )
    )
    return audit_repo.get_run(run_id)


def _persist_segment(db_path: Path, run_id="run-api", calls=2):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    repository = SQLLLMAccountingRepository(str(db_path))
    segment = AccountingSegmentV1(
        domain="learning_documents",
        run_id=run_id,
        segment_id="seg-api",
        process_nonce="proc-api",
        calls=[
            LLMCallObservationV1(
                domain="learning_documents",
                run_id=run_id,
                segment_id="seg-api",
                observation_id=index + 1,
                stage="generate" if index == 0 else "review",
                known_input_tokens=10 * (index + 1),
                usage_complete=False,
            )
            for index in range(calls)
        ],
        call_count=calls,
        sealed=True,
    )
    repository.save_segment(
        SegmentSubmissionV1(
            segment=segment,
            payload_hash=canonical_accounting_hash(segment.stable_payload()),
        )
    )
    repository.close()


def test_text_run_missing_is_404():
    tmp = tempfile.mkdtemp()
    try:
        app, *_ = _build_app(tmp)
        client = TestClient(app)
        response = client.get("/api/runs/run-missing/llm-accounting")
        assert response.status_code == 404
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_text_run_without_learner_or_profile_is_404():
    tmp = tempfile.mkdtemp()
    try:
        app, audit_repo, learner_repo, db_path, _ = _build_app(tmp)
        _create_run(audit_repo, learner_id=None)
        client = TestClient(app)
        assert client.get("/api/runs/run-api/llm-accounting").status_code == 404
        _create_run(audit_repo, learner_id="learner-api")
        # learner profile never created -> uniform 404
        assert client.get("/api/runs/run-api/llm-accounting").status_code == 404
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_text_authorized_returns_accounting_and_filters_stage():
    tmp = tempfile.mkdtemp()
    try:
        app, audit_repo, learner_repo, db_path, _ = _build_app(tmp)
        _create_run(audit_repo)
        learner_repo.save(_profile())
        _persist_segment(db_path)
        client = TestClient(app)
        response = client.get("/api/runs/run-api/llm-accounting")
        assert response.status_code == 200
        body = response.json()
        assert body["schema_version"] == "llm-accounting-v1"
        assert body["domain"] == "learning_documents"
        assert body["availability"] == "available"
        assert body["usage_complete"] is False  # unknown usage never fakes complete
        assert body["task_summary"]["observed_calls"] == 2
        assert body["calls"] == []

        filtered = client.get(
            "/api/runs/run-api/llm-accounting", params={"stage": "review", "include_calls": True}
        )
        assert filtered.status_code == 200
        filtered_body = filtered.json()
        assert filtered_body["task_summary"]["observed_calls"] == 2  # totals unchanged
        assert filtered_body["filtered_summary"]["observed_calls"] == 1
        assert all(call["stage"] == "review" for call in filtered_body["calls"])

        assert client.get(
            "/api/runs/run-api/llm-accounting", params={"stage": "nope"}
        ).status_code == 422
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_text_profile_visibility_404_for_other_user():
    tmp = tempfile.mkdtemp()
    try:
        app, audit_repo, learner_repo, db_path, _ = _build_app(tmp, current_user=_User("other"))
        _create_run(audit_repo)
        learner_repo.save(_profile())
        _persist_segment(db_path)
        client = TestClient(app)
        assert client.get("/api/runs/run-api/llm-accounting").status_code == 404
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_courseware_job_missing_is_404():
    tmp = tempfile.mkdtemp()
    try:
        app, *_ = _build_app(tmp)
        client = TestClient(app)
        response = client.get("/api/resources/courseware/jobs/run-missing/llm-accounting")
        assert response.status_code == 404
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_courseware_authorized_returns_accounting():
    tmp = tempfile.mkdtemp()
    try:
        app, audit_repo, learner_repo, db_path, courseware_service = _build_app(tmp)

        class _Job:
            status = "published"
            learner_id = "learner-api"

        courseware_service.get_job = lambda run_id: _Job()
        learner_repo.save(_profile())
        _persist_segment_for_courseware(db_path)
        client = TestClient(app)
        response = client.get("/api/resources/courseware/jobs/run-api/llm-accounting")
        assert response.status_code == 200
        body = response.json()
        assert body["domain"] == "courseware"
        assert body["task_summary"]["observed_calls"] == 1
        # Without provable execution coverage the response stays honest.
        assert body["coverage_complete"] is False
        assert "unproven_execution_coverage" in body["incomplete_reasons"]
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_old_routes_unchanged_and_new_route_registered():
    tmp = tempfile.mkdtemp()
    try:
        app, *_ = _build_app(tmp)
        paths = {route.path for route in app.routes}
        # Existing run routes stay exactly as before.
        assert "/api/runs/{run_id}" in paths
        assert "/api/runs/{run_id}/timeline" in paths
        assert "/api/runs/{run_id}/claims" in paths
        assert "/api/runs/{run_id}/events" in paths
        assert "/api/runs/{run_id}/llm-accounting" in paths
        assert "/api/resources/courseware/jobs/{run_id}" in paths
        assert "/api/resources/courseware/jobs/{run_id}/llm-accounting" in paths
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_query_endpoint_never_writes_storage():
    tmp = tempfile.mkdtemp()
    try:
        app, audit_repo, learner_repo, db_path, _ = _build_app(tmp)
        _create_run(audit_repo)
        learner_repo.save(_profile())
        _persist_segment(db_path)
        size_before = db_path.stat().st_size
        mtime_before = db_path.stat().st_mtime
        client = TestClient(app)
        for _ in range(3):
            assert client.get("/api/runs/run-api/llm-accounting").status_code == 200
        assert db_path.stat().st_size == size_before
        assert db_path.stat().st_mtime == mtime_before
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _profile():
    from app.models.learning_documents.schemas import LearnerProfile

    return LearnerProfile(
        learner_id="learner-api",
        user_id="user-1",
        learner_type="student",
        education="本科",
        major="计算机",
        learning_goal="synthetic",
    )


def _persist_segment_for_courseware(db_path: Path):
    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    repository = SQLLLMAccountingRepository(str(db_path))
    segment = AccountingSegmentV1(
        domain="courseware",
        run_id="run-api",
        segment_id="seg-cw",
        process_nonce="proc-cw",
        calls=[
            LLMCallObservationV1(
                domain="courseware",
                run_id="run-api",
                segment_id="seg-cw",
                observation_id=1,
                stage="composing",
            )
        ],
        call_count=1,
        sealed=True,
    )
    repository.save_segment(
        SegmentSubmissionV1(
            segment=segment,
            payload_hash=canonical_accounting_hash(segment.stable_payload()),
        )
    )
    repository.close()
