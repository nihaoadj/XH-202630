"""HTTP and side-effect contracts for extracted resource use cases."""

from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learning_documents import documents
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import (
    GenerateRequest,
    GenerationJobCreateResponse,
    LearnerProfile,
    LearningResource,
)
from app.services.generation.jobs import GenerationJobService
from app.services.learning_documents.resources import ResourceService


def _profile():
    return LearnerProfile(
        learner_id="use-case-learner", user_id="owner", learner_type="test",
        education="本科", major="软件", learning_goal="contract",
    )


def _publication_client(monkeypatch, *, user_id="owner", raise_server_exceptions=True, **resource_updates):
    trace = []

    class Repository(MemoryResourceRepository):
        def get(self, resource_id):
            trace.append("resource.get")
            return super().get(resource_id)

        def update_publication_decision(self, resource_id, *, publish):
            trace.append("resource.update")
            return super().update_publication_decision(resource_id, publish=publish)

    repo = Repository()
    resource = LearningResource(
        resource_id="claim-resource", learner_id=_profile().learner_id,
        topic="contract", resource_type="讲义", difficulty="初级", run_id="claim-run",
        knowledge_points=[], source_refs=[],
        claim_metric_status="complete", claim_factual_pass_rate=0.9,
        claim_publish_decision_pending=True, claim_publish_decision="pending",
    ).model_copy(update=resource_updates)
    repo.save(resource, resource.learner_id, resource.topic)

    def provider(name, value):
        def resolve():
            trace.append(name)
            return value
        return resolve

    def claims(run_id):
        trace.append("claims.get")
        assert run_id == "claim-run"
        return SimpleNamespace(resource_metrics={
            "claim-resource": SimpleNamespace(contradicted_claim_total=0),
        })

    events = []

    def append_event(*args, **kwargs):
        trace.append("audit.append")
        if any(item[1].get("event_id") == kwargs.get("event_id") for item in events):
            return
        events.append((args, kwargs))

    monkeypatch.setattr(documents, "get_settings", provider(
        "settings", SimpleNamespace(claim_user_review_min_factual_pass_rate=0.8),
    ))
    app = FastAPI()

    @app.middleware("http")
    async def current_user(request, call_next):
        request.state.current_user = SimpleNamespace(user_id=user_id)
        return await call_next(request)

    app.container = SimpleNamespace(
        resource_service=provider("resource.provider", ResourceService(repo)),
        profile_service=provider("profile.provider", SimpleNamespace(get=lambda _id: _profile())),
        run_query_service=provider("claims.provider", SimpleNamespace(get_claims=claims)),
        audit_repository=provider("audit.provider", SimpleNamespace(append_event=append_event)),
    )
    app.include_router(documents.router, prefix="/api/resources")
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), trace, events


def test_claim_publication_preserves_lazy_dependencies_commit_event_and_repeat(monkeypatch):
    client, trace, events = _publication_client(monkeypatch)
    path = "/api/resources/items/claim-resource/claim-publication-decision"
    response = client.post(path, json={"publish": True})
    assert response.status_code == 200
    assert response.json()["resource"]["claim_publish_decision"] == "published_by_user"
    assert trace == [
        "resource.provider", "resource.get", "profile.provider", "settings",
        "claims.provider", "claims.get", "resource.update", "audit.provider", "audit.append",
    ]
    assert events[0][0][0] == "claim-run"
    assert events[0][1]["payload"] == {
        "resource_id": "claim-resource", "resource_type": "讲义",
        "publication_status": "published", "claim_publish_decision": "published_by_user",
    }
    trace.clear()
    assert client.post(path, json={"publish": True}).status_code == 200
    assert trace == ["resource.provider", "resource.get", "profile.provider", "audit.provider", "audit.append"]
    assert len(events) == 1
    conflict = client.post(path, json={"publish": False})
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "该资源当前不处于待用户决策状态"


@pytest.mark.parametrize("commit_before_error", [False, True])
def test_claim_retry_restores_missing_event_without_repeating_decision(monkeypatch, commit_before_error):
    client, trace, events = _publication_client(monkeypatch, raise_server_exceptions=False)
    audit = client.app.container.audit_repository()
    original = audit.append_event
    failed = False

    def intermittent(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            if commit_before_error:
                original(*args, **kwargs)
            raise RuntimeError("synthetic audit outage")
        return original(*args, **kwargs)

    audit.append_event = intermittent
    path = "/api/resources/items/claim-resource/claim-publication-decision"
    assert client.post(path, json={"publish": True}).status_code == 500
    trace.clear()
    retried = client.post(path, json={"publish": True})
    assert retried.status_code == 200
    assert retried.json()["resource"]["claim_publish_decision"] == "published_by_user"
    assert "resource.update" not in trace
    assert "settings" not in trace and "claims.get" not in trace
    assert len(events) == 1
    assert events[0][1]["event_id"].startswith("evt_")


def test_claim_publication_replay_preserves_a_legacy_random_event_id(monkeypatch):
    from datetime import datetime, timezone
    from app.db.audit.memory import MemoryAuditRepository
    from app.models.shared.persistence import CreateRunCommand, WorkflowEventType, canonical_hash

    client, trace, _ = _publication_client(
        monkeypatch, claim_publish_decision_pending=False,
        claim_publish_decision="published_by_user", publication_status="published",
    )
    audit = MemoryAuditRepository()
    snapshot = {"learner_id": _profile().learner_id, "topic": "contract"}
    audit.create_run(CreateRunCommand(
        run_id="claim-run", learner_id=_profile().learner_id, topic="contract",
        request_snapshot=snapshot, request_hash=canonical_hash(snapshot),
    ))
    audit.append_event(
        "claim-run", WorkflowEventType.RESOURCE_PUBLICATION_DECIDED,
        payload={
            "resource_id": "claim-resource", "resource_type": "讲义",
            "publication_status": "published", "claim_publish_decision": "published_by_user",
        },
        status="published", occurred_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        event_id="legacy-random-event-id",
    )
    before = audit.list_events("claim-run")
    client.app.container.audit_repository = lambda: audit
    response = client.post(
        "/api/resources/items/claim-resource/claim-publication-decision", json={"publish": True},
    )
    assert response.status_code == 200
    assert audit.list_events("claim-run") == before
    assert "resource.update" not in trace


@pytest.mark.parametrize("updates,detail,settings_called", [
    ({"claim_metric_status": "pending"}, "Claim 审核尚未完成", False),
    ({"claim_factual_pass_rate": None}, "事实 Claim 通过率未达到用户决策阈值", False),
    ({"claim_factual_pass_rate": 0.7}, "事实 Claim 通过率未达到用户决策阈值", True),
])
def test_claim_conflict_keeps_status_message_and_short_circuit(monkeypatch, updates, detail, settings_called):
    client, trace, events = _publication_client(monkeypatch, **updates)
    response = client.post("/api/resources/items/claim-resource/claim-publication-decision", json={"publish": True})
    assert response.status_code == 409
    assert response.json()["detail"] == detail
    assert ("settings" in trace) == settings_called
    assert "claims.provider" not in trace
    assert not events


def test_claim_publication_authentication_still_precedes_use_case(monkeypatch):
    client, trace, events = _publication_client(monkeypatch, user_id="another-user")
    response = client.post("/api/resources/items/claim-resource/claim-publication-decision", json={"publish": True})
    assert response.status_code == 404
    assert response.json()["detail"] == "资源不存在"
    assert trace == ["resource.provider", "resource.get", "profile.provider"]
    assert not events


def test_continuation_keeps_feedback_supersede_and_background_order(monkeypatch):
    trace = []
    profile = _profile()
    original = GenerateRequest(
        learner_id=profile.learner_id, topic="contract", resource_types=["讲义"],
        constraints={"feedback_attempt_id": "attempt", "feedback_decision_id": "decision"},
    )

    class Jobs(GenerationJobService):
        def __init__(self):
            pass

        def list_jobs(self, learner_id):
            trace.append("jobs.list")
            return SimpleNamespace(items=[SimpleNamespace(
                run_id="source", batch_id="batch", request_payload=original.model_dump(),
            )])

        def create_job(self, learner, req, *, batch_id):
            trace.append("jobs.create")
            assert req.constraints["replacement_resource_types"] == ["讲义"]
            assert req.constraints["continuation_context"] == []
            return GenerationJobCreateResponse(
                run_id="child", batch_id=batch_id, learner_id=learner.learner_id, topic=req.topic,
            )

        def mark_superseded(self, source_run_id, child_run_id):
            trace.append("jobs.supersede")
            assert (source_run_id, child_run_id) == ("source", "child")

        def run_job(self, learner, req, run_id, batch_id):
            trace.append("jobs.run")
            assert (run_id, batch_id) == ("child", "batch")

    def feedback_repo():
        trace.append("feedback.provider")
        return SimpleNamespace(feedback_loop_repo=SimpleNamespace(
            get_followup_relation=lambda _id: trace.append("feedback.get") or {"relation_id": "relation"},
            attach_followup=attach,
        ))

    def attach(**kwargs):
        trace.append("feedback.attach")
        assert kwargs["source_relation_id"] == "relation"
        assert kwargs["relation_type"] == "retry"
        assert kwargs["child_run_id"] == "child"

    def resources():
        trace.append("resource.provider")
        return ResourceService(MemoryResourceRepository())

    monkeypatch.setattr(documents, "get_settings", lambda: object())
    monkeypatch.setattr(documents, "build_health_report", lambda _: SimpleNamespace(status="ready", error_codes=[]))
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: SimpleNamespace(get=lambda _: profile),
        generation_job_service=lambda: Jobs(), resource_service=resources, feedback_service=feedback_repo,
    )
    app.include_router(documents.router, prefix="/api/resources")
    response = TestClient(app).post("/api/resources/batches/batch/continuations", json={
        "learner_id": profile.learner_id, "resource_types": ["讲义"], "source_run_id": "source",
        "instructions": "重新生成", "replace_existing_types": True, "replace_source_run": True,
    })
    assert response.status_code == 200
    assert response.json()["run_id"] == "child"
    assert trace == [
        "jobs.list", "resource.provider", "jobs.create", "feedback.provider", "feedback.get",
        "feedback.provider", "feedback.attach", "jobs.supersede", "jobs.run",
    ]
