"""API contract tests for the read-only resource-quality endpoint (T48 R01).

The endpoint is deliberately separate from the learning-resource read model and
the legacy report payload.  These tests pin the contract-level guarantees:
authorization, 404/422 semantics, ordering stability and the fact that a GET
never writes a business row, event or hash.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.runs import run_queries
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.learners.repository import create_learner_repository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.services.learners.profiles import ProfileService
from app.services.reviews.quality_query import ResourceQualityQueryService
from app.services.runs.queries import RunQueryService

LEARNER_ID = "learner-t48"
USER_ID = "user-t48"
RUN_ID = "run-t48"


class _User:
    def __init__(self, user_id: str):
        self.user_id = user_id


def _application_error_handler(request: Request, exc: ApplicationError):
    from fastapi.responses import JSONResponse

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error", "code": exc.code.value,
            "message": exc.public_message, "detail": None,
        },
    )


def _build_app(*, current_user=_User(USER_ID), run_id: str = RUN_ID):
    audit = MemoryAuditRepository()
    resources = MemoryResourceRepository()
    claims = MemoryClaimRepository()
    learners = create_learner_repository(db_type="memory")
    learners.save(LearnerProfile(
        learner_id=LEARNER_ID, user_id=USER_ID, learner_type="student",
        education="本科", major="软件工程", knowledge_base_id="kb-1",
        learning_goal="通过考试",
    ))

    now = datetime.now(timezone.utc)
    snapshot = {"topic": "T48", "include_review": True, "include_claim_check": False}
    audit.create_run(CreateRunCommand(
        run_id=run_id, learner_id=LEARNER_ID, knowledge_base_id="kb-1",
        topic="T48", request_snapshot=snapshot, request_hash=canonical_hash(snapshot),
        owner_instance_id="test", lease_expires_at=now + timedelta(seconds=60),
        occurred_at=now,
    ))

    run_service = RunQueryService(
        repository=audit, resource_repository=resources, claim_repository=claims,
        feedback_loop_repository=None,
    )
    quality_service = ResourceQualityQueryService(
        audit_repository=audit, resource_repository=resources,
        claim_repository=claims, generation_job_repository=None,
    )

    app = FastAPI()
    app.container = SimpleNamespace(
        run_query_service=lambda: run_service,
        profile_service=lambda: ProfileService(learners),
        resource_quality_query_service=lambda: quality_service,
    )
    app.add_exception_handler(ApplicationError, _application_error_handler)

    def _set_user(request: Request):
        if current_user is not None:
            request.state.current_user = current_user

    app.include_router(
        run_queries.router, prefix="/api/runs", dependencies=[Depends(_set_user)],
    )
    return app, audit, resources, claims


def _save_resource(repository, resource_id: str, *, version: int = 1) -> None:
    repository.save(
        LearningResource(
            resource_id=resource_id, resource_type="讲义", difficulty="中级",
            topic="T48", content_text="内容", knowledge_points=["node-1"],
            source_refs=[], run_id=RUN_ID, version=version,
            resource_spec_id=f"spec-{resource_id}",
            publication_status="published",
        ),
        LEARNER_ID, "T48", run_id=RUN_ID,
    )


def test_missing_run_is_a_uniform_404():
    app, *_ = _build_app()
    client = TestClient(app)
    response = client.get("/api/runs/run-does-not-exist/resource-quality")
    assert response.status_code == 404


def test_run_of_another_user_is_not_visible():
    app, *_ = _build_app(current_user=_User("someone-else"))
    client = TestClient(app)
    response = client.get(f"/api/runs/{RUN_ID}/resource-quality")
    assert response.status_code == 404


def test_resource_id_longer_than_the_query_limit_is_422():
    app, *_ = _build_app()
    client = TestClient(app)
    response = client.get(
        f"/api/runs/{RUN_ID}/resource-quality", params={"resource_id": "x" * 129},
    )
    assert response.status_code == 422


def test_empty_run_is_not_applicable_instead_of_zero():
    app, *_ = _build_app()
    client = TestClient(app)
    response = client.get(f"/api/runs/{RUN_ID}/resource-quality")
    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"] == RUN_ID
    assert payload["items"] == []
    assert payload["summary"]["coverage"]["status"] == "not_applicable"
    assert payload["summary"]["coverage"]["value"] is None
    assert payload["summary"]["resource_total"] == 0
    assert payload["availability"] == "unavailable"


def test_items_are_ordered_and_filterable_and_never_measured_without_audit():
    app, _, resources, _ = _build_app()
    _save_resource(resources, "resource-b")
    _save_resource(resources, "resource-a")
    client = TestClient(app)

    response = client.get(f"/api/runs/{RUN_ID}/resource-quality")
    assert response.status_code == 200
    payload = response.json()
    assert [item["resource_id"] for item in payload["items"]] == [
        "resource-a", "resource-b",
    ]
    # No ordinary ledger exists, so nothing may be reported as measured and
    # the resources stay in the distinct "legacy missing" bucket.
    for item in payload["items"]:
        assert item["coverage"]["status"] == "legacy_unavailable"
        assert item["coverage"]["value"] is None
        assert item["hallucination"]["status"] in {"not_requested", "legacy_unavailable"}
    assert payload["summary"]["coverage"]["value"] is None
    assert payload["summary"]["coverage_buckets"]["legacy_unavailable"] == 2
    assert payload["summary"]["coverage_buckets"]["unavailable"] == 0
    assert payload["summary"]["claim_buckets"]["legacy_unavailable"] == 2
    assert payload["summary"]["claim_buckets"]["not_requested"] == 0

    filtered = client.get(
        f"/api/runs/{RUN_ID}/resource-quality", params={"resource_id": "resource-b"},
    )
    assert filtered.status_code == 200
    assert [item["resource_id"] for item in filtered.json()["items"]] == ["resource-b"]
    # A filtered response describes exactly the returned items; it never
    # borrows the sibling resource's counts.
    assert filtered.json()["summary"]["resource_total"] == 1


def test_unknown_resource_filter_is_404_not_empty_items():
    app, *_ = _build_app()
    client = TestClient(app)
    response = client.get(
        f"/api/runs/{RUN_ID}/resource-quality", params={"resource_id": "nope"},
    )
    assert response.status_code == 404


def test_get_never_writes_business_rows_events_or_hashes():
    app, audit, resources, claims = _build_app()
    _save_resource(resources, "resource-a")
    run_before = audit.get_run(RUN_ID)
    steps_before = audit.list_steps(RUN_ID)
    checkpoints_before = audit.list_checkpoints(RUN_ID)
    claim_rows_before = claims.list_claims_by_runs([RUN_ID])
    client = TestClient(app)

    for _ in range(2):
        assert client.get(f"/api/runs/{RUN_ID}/resource-quality").status_code == 200

    run_after = audit.get_run(RUN_ID)
    assert run_after.status == run_before.status
    assert run_after.row_version == run_before.row_version
    assert run_after.last_event_sequence == run_before.last_event_sequence
    assert run_after.updated_at == run_before.updated_at
    assert audit.list_steps(RUN_ID) == steps_before
    assert audit.list_checkpoints(RUN_ID) == checkpoints_before
    assert claims.list_claims_by_runs([RUN_ID]) == claim_rows_before
    assert [item.resource_id for item in resources.list_by_run(RUN_ID)] == ["resource-a"]
