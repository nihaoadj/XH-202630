"""Round API shape: review-only corrections and the closed legacy submit entry."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.feedback import feedback as feedback_api
from app.api.feedback import rounds as rounds_api
from app.core.security.errors import ApplicationError, ErrorCode
from app.main import application_exception_handler
from app.models.learning_documents.schemas import GenerateRequest
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from tests.integration.services.test_round_generation import (
    create_payload, dual_round, fixture, publish, submit,
)


def api_for(service, monkeypatch):
    app = FastAPI()
    app.add_exception_handler(ApplicationError, application_exception_handler)
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(service.learners),
        resource_service=lambda: ResourceService(service.feedback.resource_repo),
        feedback_service=lambda: service.feedback,
        knowledge_service=lambda: service.feedback.mastery_service.knowledge_service,
        round_learning_service=lambda: service,
    )
    scheduled = []
    monkeypatch.setattr(rounds_api, "schedule_round", lambda *args, **kwargs: scheduled.append(args[3]))
    app.include_router(feedback_api.router, prefix="/api/feedback")
    app.include_router(rounds_api.router, prefix="/api/feedback")
    return TestClient(app), scheduled


def test_review_only_correction_api_reports_the_round_primary(monkeypatch):
    service, profile = fixture()
    result = dual_round(service, profile)
    submitted = submit(service, profile, result, "dual-submit", "B")
    review = next(node for node in submitted.nodes if node.role == "review")
    client, scheduled = api_for(service, monkeypatch)

    response = client.post(f"/api/feedback/rounds/{result.round_id}/corrections", json={
        "learner_id": "learner", "selection_key": "review-only-api",
        "targets": [{"node_id": review.node_id, "source_attempt_id": submitted.attempt_id}],
    })

    assert response.status_code == 202
    body = response.json()
    assert body["primary_node_id"] == result.primary_node_id
    assert body["primary_default_run_id"] is None
    assert [member["role"] for member in body["members"]] == ["review"]
    assert len(scheduled) == 1


def test_round_bound_run_cannot_submit_through_the_legacy_entry(monkeypatch):
    service, profile = fixture()
    created = service.create(profile, create_payload())
    publish(service, created)
    run_id = created.members[0].job_ids[0]
    client, _ = api_for(service, monkeypatch)
    resource = service.feedback.resource_repo.list_by_run(run_id)[0]

    response = client.post("/api/feedback/attempts/run/submit", json={
        "learner_id": "learner", "run_id": run_id, "source_resource_id": resource.resource_id,
        "idempotency_key": "legacy-bypass", "expected_profile_version": profile.profile_version,
        "submitted_at": datetime(2026, 11, 7, tzinfo=timezone.utc).isoformat(),
        "answers": [{"question_id": "q-a", "answer": "A"}],
    })

    assert response.status_code == 422
    assert response.json()["code"] == ErrorCode.ROUND_ASSESSMENT_INVALID.value
    assert created.round_id in response.json()["message"]


def test_unbound_legacy_run_is_not_blocked_by_the_round_guard():
    service, profile = fixture()
    legacy = service.feedback.generation_job_service.create_job(
        profile,
        GenerateRequest(learner_id="learner", knowledge_base_id="kb", topic="a", target_skill_nodes=["a"],
                        resource_types=["讲义"], difficulty_preference="初级", include_review=True),
        run_id="legacy-run", batch_id="legacy-batch", submission_hash="legacy-hash",
    )
    service.feedback.require_legacy_run_assessment([legacy.run_id])

    bound = service.create(profile, create_payload("bound-key"))
    with pytest.raises(ApplicationError) as caught:
        service.feedback.require_legacy_run_assessment([bound.members[0].job_ids[0]])
    assert caught.value.code == ErrorCode.ROUND_ASSESSMENT_INVALID


@pytest.mark.parametrize("expired", [False, True])
def test_result_http_status_distinguishes_live_and_expired_scoring(expired, monkeypatch):
    from tests.integration.services.test_round_failure_recovery import claim_scoring, freeze_submission

    service, profile = fixture()
    created = service.create(profile, create_payload())
    publish(service, created)
    payload = freeze_submission(service, profile, created)
    saved = claim_scoring(service, payload, expired=expired)
    client, _ = api_for(service, monkeypatch)
    base = f"/api/feedback/rounds/{created.round_id}/stages/{created.stage_id}"

    response = client.get(base + "/result")

    assert response.status_code == (200 if expired else 202)
    assert response.json()["state"] == ("not_submitted" if expired else "grading")
    assert service.repository.one("learning_round_evaluation_sessions", session_id=payload.session_id) == saved
    if expired:
        submitted = client.post(base + "/attempts", json=payload.model_dump(mode="json"))
        assert submitted.status_code == 200
        assert client.post(base + "/attempts", json=payload.model_dump(mode="json")).json() == submitted.json()
        assert len(service.feedback.feedback_loop_repo.list_attempts(profile.learner_id)) == 1
