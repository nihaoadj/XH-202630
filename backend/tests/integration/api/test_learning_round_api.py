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
from tests.integration.services.test_round_legacy_adapter import legacy_attempt


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


@pytest.mark.parametrize("sql", [False, True])
def test_candidates_restore_preexisting_correction_choice_without_browser_storage(sql, monkeypatch):
    from app.models.feedback.rounds import RoundCorrectionSelectionV1
    from app.services.feedback.round_corrections import RoundCorrections
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    result = submit(service, profile, created, "restore-choice", "B")
    current = service.learners.get("learner")
    client, _ = api_for(service, monkeypatch)
    url = f"/api/feedback/rounds/{created.round_id}/candidates?source_attempt_id={result.attempt_id}"
    assert client.get(url).json()["confirmed_selection"] is None
    target = {"node_id": created.members[0].node_id, "source_attempt_id": result.attempt_id}
    selected = RoundCorrections(service).create(current, created.round_id, RoundCorrectionSelectionV1(
        learner_id="learner", selection_key="historical-choice", targets=[target], include_claim_check=True,
    ))
    response = client.get(url)
    assert response.status_code == 200, response.text
    choice = response.json()["confirmed_selection"]
    assert choice["route"] == "correction" and choice["label"] == "强化巩固"
    assert choice["stageId"] == selected.stage_id
    assert choice["payload"]["targets"] == [target]
    assert choice["payload"]["include_claim_check"] is True
    assert choice["nodes"][0]["skill_node_id"] == created.members[0].node_id
    # Re-reading never creates another stage or depends on local storage.
    assert client.get(url).json()["confirmed_selection"] == choice
    assert client.get(f"/api/feedback/rounds/{created.round_id}/candidates?source_attempt_id=foreign").status_code == 404


@pytest.mark.parametrize("sql", [False, True])
def test_retake_reuses_questions_and_keeps_both_formal_results(sql, monkeypatch):
    from app.models.shared.llm import LLMCallContext, LLMBudgetScope
    from app.services.feedback.round_budget import RoundBudgetGuard
    from tests.integration.services.test_round_failure_recovery import freeze_submission

    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    first = freeze_submission(service, profile, created)
    client, scheduled = api_for(service, monkeypatch)
    base = f"/api/feedback/rounds/{created.round_id}/stages/{created.stage_id}"
    first_body = first.model_dump(mode="json")
    first_result = client.post(base + "/attempts", json=first_body).json()
    original = client.post(base + "/evaluation-session", json={"learner_id": profile.learner_id}).json()

    request = {"learner_id": profile.learner_id, "retake_from_session_id": first.session_id}
    response = client.post(base + "/evaluation-session", json=request)
    assert response.status_code == 200, response.text
    retake = response.json()
    assert retake["session_id"] != first.session_id
    assert retake["groups"] == original["groups"]
    assert client.post(base + "/evaluation-session", json=request).json() == retake
    assert client.post(base + "/evaluation-session", json={"learner_id": profile.learner_id}).json() == retake
    assert client.get(base + "/result").json()["state"] == "not_submitted"
    assert client.post(base + "/attempts", json=first_body).json() == first_result
    guard = RoundBudgetGuard(service.repository)
    context = LLMCallContext(run_id=created.members[0].job_ids[0], step_id="retake-test",
                             node_name="retake-test", schema_name="FeedbackAnalysis", generation_attempt=1,
                             budget_scope=LLMBudgetScope(scope_id=retake["session_id"], stage_id=created.stage_id, kind="assessment"),
                             call_purpose="assessment")
    assert guard.reserve(context, 1, 100, 1)

    second = {**first_body, "session_id": retake["session_id"], "manifest_hash": retake["manifest_hash"],
              "expected_profile_version": first_result["profile_version"], "idempotency_key": "new-retake-submit"}
    second_response = client.post(base + "/attempts", json=second)
    assert second_response.status_code == 200, second_response.text
    second_result = second_response.json()
    assert second_result["attempt_id"] != first_result["attempt_id"]
    assert client.get(base + "/result").json() == second_result
    assert client.get(base + "/result", params={"session_id": first.session_id}).json()["attempt_id"] == first_result["attempt_id"]
    assert len(service.feedback.list_results(profile.learner_id)) == 2
    assert all(item.analysis for item in service.feedback.list_results(profile.learner_id))
    assert scheduled == []


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


def test_unbound_feedback_can_select_one_primary_and_one_qualified_review(monkeypatch):
    service, profile = fixture()
    previous = legacy_attempt(service, profile)
    assert "round_context" not in previous.attempt.metadata
    client, scheduled = api_for(service, monkeypatch)
    endpoint = "/api/feedback/rounds/next/candidates"
    params = {"learner_id": profile.learner_id, "source_attempt_id": previous.attempt.attempt_id}

    response = client.get(endpoint, params=params)
    assert response.status_code == 200
    candidates = response.json()
    assert [node["skill_node_id"] for node in candidates["generation_options"]["learn_new_knowledge"]] == ["b"]
    assert [node["skill_node_id"] for node in candidates["eligible_review_nodes"]] == ["a"]
    assert candidates["correction_targets"] == []
    assert client.get(endpoint, params={**params, "source_attempt_id": "unknown"}).status_code == 404
    assert client.get(endpoint, params={**params, "learner_id": "unknown"}).status_code == 404

    payload = {
        **params, "primary_node_id": "b", "primary_learning_intent": "learn_new_knowledge",
        "primary_resource_types": ["讲义"], "review_node_id": "a", "selection_key": "next-from-legacy",
    }
    selected = client.post("/api/feedback/rounds/next/select", json=payload)
    assert selected.status_code == 202
    assert [(member["role"], member["node_id"], member["resource_types"]) for member in selected.json()["members"]] == [
        ("primary", "b", ["讲义"]), ("review", "a", ["复习清单", "分阶测试题"]),
    ]
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


@pytest.mark.parametrize("sql", [False, True])
def test_candidates_restore_saved_next_round_nodes_and_resources(sql, monkeypatch):
    from app.models.feedback.rounds import RoundNextSelectionV1
    service, profile = fixture(sql)
    created = service.create(profile, create_payload())
    publish(service, created)
    result = submit(service, profile, created, "next-confirmation")
    current = service.learners.get("learner")
    selected = service.next(current, RoundNextSelectionV1(
        learner_id="learner", source_attempt_id=result.attempt_id, selection_key="saved-next",
        primary_learning_intent="learn_new_knowledge", primary_node_id="b", primary_resource_types=["讲义", "案例分析"],
    ))
    client, _ = api_for(service, monkeypatch)
    response = client.get(f"/api/feedback/rounds/{created.round_id}/candidates?source_attempt_id={result.attempt_id}")
    assert response.status_code == 200, response.text
    choice = response.json()["confirmed_selection"]
    assert choice["route"] == "learning" and choice["roundId"] == selected.round_id
    assert choice["payload"]["primary_node_id"] == "b"
    assert choice["payload"]["primary_resource_types"] == ["讲义", "案例分析"]
    assert choice["nodes"][0]["skill_node_id"] == "b"
