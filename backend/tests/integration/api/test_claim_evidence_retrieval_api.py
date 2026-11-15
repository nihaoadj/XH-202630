"""API contract for the read-only Claim evidence retrieval summary."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

from app.api.runs import run_queries
from app.core.security.errors import ApplicationError
from app.db.audit.memory import MemoryAuditRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.supplement import MemoryClaimSupplementRepository
from app.db.learners.repository import create_learner_repository
from app.models.learning_documents.schemas import LearnerProfile
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
)
from app.models.shared.persistence import CreateRunCommand, canonical_hash
from app.services.learners.profiles import ProfileService
from app.services.reviews.claim_evidence_retrieval_query import (
    ClaimEvidenceRetrievalQueryService,
)
from app.services.runs.queries import RunQueryService

LEARNER_ID = "learner-t50"
USER_ID = "user-t50"
RUN_ID = "run-t50"
NOW = datetime.now(timezone.utc)


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


def _build_app(*, current_user=_User(USER_ID)):
    audit = MemoryAuditRepository()
    claims = MemoryClaimRepository()
    learners = create_learner_repository(db_type="memory")
    learners.save(LearnerProfile(
        learner_id=LEARNER_ID, user_id=USER_ID, learner_type="student",
        education="本科", major="软件工程", knowledge_base_id="kb-1",
        learning_goal="通过考试",
    ))
    snapshot = {
        "topic": "T50", "include_review": True, "include_claim_check": True,
        "include_claim_evidence_retrieval": True,
    }
    audit.create_run(CreateRunCommand(
        run_id=RUN_ID, learner_id=LEARNER_ID, knowledge_base_id="kb-1",
        topic="T50", request_snapshot=snapshot, request_hash=canonical_hash(snapshot),
        owner_instance_id="test", lease_expires_at=NOW + timedelta(seconds=60),
        occurred_at=NOW,
    ))
    supplement = MemoryClaimSupplementRepository(
        claim_repository=claims, audit_repository=audit,
    )
    supplement.create_session(ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32,
        run_id=RUN_ID, resource_id="res-1", resource_version=1, review_id="rev-1",
        content_hash="a" * 64, policy_hash="b" * 64,
        base_evidence_set_hash="c" * 64, initial_judgement_hash="d" * 64,
        target_claim_ids=["clm_" + "1" * 32],
        status=ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
        reason_code="no_new_evidence",
        completed_at=NOW, updated_at=NOW,
    ))
    run_service = RunQueryService(
        repository=audit, resource_repository=None, claim_repository=claims,
        feedback_loop_repository=None, supplement_repository=supplement,
    )
    query_service = ClaimEvidenceRetrievalQueryService(
        audit_repository=audit, claim_repository=claims,
        supplement_repository=supplement,
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        run_query_service=lambda: run_service,
        profile_service=lambda: ProfileService(learners),
        claim_evidence_retrieval_query_service=lambda: query_service,
    )
    app.add_exception_handler(ApplicationError, _application_error_handler)

    def _set_user(request: Request):
        if current_user is not None:
            request.state.current_user = current_user

    app.include_router(
        run_queries.router, prefix="/api/runs", dependencies=[Depends(_set_user)],
    )
    return app


def test_summary_returns_the_committed_session_without_starting_work():
    client = TestClient(_build_app())
    response = client.get(f"/api/runs/{RUN_ID}/claim-evidence-retrieval")

    assert response.status_code == 200
    payload = response.json()
    assert payload["contract_version"] == "claim-evidence-retrieval/v1"
    assert payload["requested"] is True
    assert payload["status"] == "no_new_evidence"
    assert payload["reason_code"] == "no_new_evidence"
    assert payload["sessions"][0]["status"] == "no_new_evidence"
    # No private prompt, key or raw error field is exposed.
    serialized = response.text
    assert "prompt" not in serialized
    assert "api_key" not in serialized


def test_missing_run_is_a_uniform_404():
    client = TestClient(_build_app())
    response = client.get("/api/runs/run-missing/claim-evidence-retrieval")
    assert response.status_code == 404


def test_run_of_another_user_is_not_visible():
    client = TestClient(_build_app(current_user=_User("someone-else")))
    response = client.get(f"/api/runs/{RUN_ID}/claim-evidence-retrieval")
    assert response.status_code == 404


def test_resource_id_over_the_query_limit_is_422():
    client = TestClient(_build_app())
    response = client.get(
        f"/api/runs/{RUN_ID}/claim-evidence-retrieval",
        params={"resource_id": "x" * 129},
    )
    assert response.status_code == 422
