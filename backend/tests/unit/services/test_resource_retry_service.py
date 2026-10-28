"""Frozen single-resource retry service, delivery and HTTP contracts (no live models)."""
import json
from dataclasses import replace
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.generation import generation as api
from app.core.retrieval.knowledge_ids import normalize_text, query_hash, sha256_hex
from app.core.security.errors import ApplicationError
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, KnowledgeBaseORM, LearnerProfileORM, UserProfileORM
from app.models.generation.dispatch import RESOURCE_RETRY_WORKFLOW_VERSION
from app.main import application_exception_handler
from app.models.generation.resource_retry import ResourceRetryContext
from app.models.knowledge.knowledge import EvidenceItem, ScoreKind, SourceLocator, SourceType
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.agent_contracts import ResourceSpec
from app.models.shared.persistence import PersistedEvidenceSnapshot, WorkflowCheckpoint, canonical_hash
from app.services.generation.jobs import GenerationJobService
from app.services.generation.resource_retry import prepare_resource_retry


def source_state(repo=None):
    learner = LearnerProfile(learner_id="learner", user_id="owner", learner_type="test",
                             education="本科", major="软件", learning_goal="frozen goal", knowledge_base_id="kb")
    req = GenerateRequest(learner_id="learner", topic="retry", knowledge_base_id="kb",
                          resource_types=["讲义"], profile_focus_mode="off", include_review=True,
                          include_claim_check=True, difficulty_preference="初级")
    jobs = repo if repo is not None else MemoryGenerationJobRepository()
    resources = MemoryResourceRepository()
    now = datetime.now(timezone.utc)
    locator = SourceLocator(knowledge_base_id="kb", document_id="doc", document_version="v1", chunk_id="chunk",
                            source_type=SourceType.MARKDOWN, source_path="teaching/test.md", title="synthetic", line_start=1, line_end=1)
    item = EvidenceItem(evidence_id="evidence", knowledge_base_id="kb", document_id="doc", document_version="v1",
                        chunk_id="chunk", query="synthetic query", query_hash=query_hash("synthetic query"),
                        query_rank=1, rank=1, raw_score=0.8, score_kind=ScoreKind.SIMILARITY, normalized_score=0.8,
                        excerpt="synthetic evidence", excerpt_hash=sha256_hex(normalize_text("synthetic evidence")),
                        locator=locator, config_hash="a" * 64, retrieved_at=now)
    evidence = PersistedEvidenceSnapshot.from_evidence(item, run_id="source", retrieval_step_id="retrieve")
    spec = ResourceSpec(resource_spec_id=str(uuid4()), resource_family_id=str(uuid4()), resource_type="讲义",
                        learning_objective="frozen objective", knowledge_points=["node"], evidence_ids=[item.evidence_id],
                        node_evidence_map={"node": [item.evidence_id]}, difficulty="初级",
                        representations=[{"representation": "text", "max_output_tokens": 1024}], display_order=1)
    resources.save_spec(ResourceSpecRecord(run_id="source", **spec.model_dump(mode="json")))
    parent = LearningResource(resource_id="parent", learner_id="learner", run_id="source", batch_id="batch",
                              resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
                              resource_type="讲义", topic="retry", difficulty="初级", content_text="old draft",
                              knowledge_points=["node"], source_refs=[], publication_status="unpublished")
    resources.save(parent, "learner", "retry", run_id="source", batch_id="batch")
    resources.upsert_execution(ResourceExecutionRecord(run_id="source", resource_spec_id=spec.resource_spec_id,
                               resource_type="讲义", state="failed", resource_id="parent", attempt=3,
                               agent_name="text", prompt_version="v1", artifact_format="markdown"))
    projection = {"run_id": "source", "learner_id": "learner", "knowledge_base_id": "kb",
                  "resource_specs": [spec.model_dump(mode="json")], "evidence_ids": [item.evidence_id],
                  "diagnosis": {"summary": "frozen diagnosis"}, "learning_plan": {"goal": "frozen plan"},
                  "retrieval_config_hash": "a" * 64, "retrieval_strategy_version": "legacy"}
    checkpoint = WorkflowCheckpoint(checkpoint_id="checkpoint", run_id="source", step_id="finalize", step_sequence=7,
                                    event_sequence=9, node_name="finalize", state_projection=projection,
                                    state_hash=canonical_hash(projection), created_at=now)
    s = SimpleNamespace(learner=learner, req=req, repo=jobs, resources=resources, evidence=evidence, spec=spec,
                        checkpoint=checkpoint, calls=[])
    s.audit = SimpleNamespace(list_checkpoints=lambda run: [s.checkpoint], list_evidence=lambda run: [s.evidence],
                             list_reviews_by_run=lambda run: [{"resource_id": "parent", "suggestion": "repair",
                                 "revision_instructions": [{"target_resource_type": "讲义", "instruction": "repair"},
                                                           {"target_resource_type": "实操指南", "instruction": "ignore"}]}])

    def generate(learner, request, **kwargs):
        s.calls.append((learner, request, kwargs))
        return SimpleNamespace(resources=[], workflow_status="completed")

    s.generation = SimpleNamespace(resource_repo=resources, audit_repo=s.audit, generate_with_run_id=generate)
    s.service = GenerationJobService(jobs, s.generation, dispatch_mode="worker" if repo is not None else "background")
    jobs.create(run_id="source", batch_id="batch", learner_id="learner", topic=req.topic, knowledge_base_id="kb",
                request_payload=req.model_dump(mode="json"), dispatch_snapshot=s.service._dispatch_snapshot(learner, req))
    jobs.mark_completed("source", ["parent"])
    return s


@pytest.fixture
def source():
    return source_state()


def prepare(s, **overrides):
    return prepare_resource_retry(s.service, overrides.get("learner", s.learner), overrides.get("run_id", "source"),
                                  overrides.get("spec_id", s.spec.resource_spec_id), overrides.get("representation", "text"))


@pytest.mark.parametrize("status", ["completed", "failed"])
def test_prepare_child_is_frozen_single_spec_and_source_unchanged(source, status):
    s = source
    if status == "failed":
        s.repo.mark_failed("source", "exhausted")
    before = s.repo.get("source").model_dump(mode="json")
    parent = s.resources.get("parent").model_dump(mode="json")
    context = prepare(s)
    assert context.request.resource_types == ["讲义"]
    assert context.diagnosis == {"summary": "frozen diagnosis"}
    assert context.learning_plan == {"goal": "frozen plan"}
    assert context.spec == s.spec and context.evidence == [s.evidence]
    assert len(context.revision_feedback["revision_instructions"]) == 1
    child, req = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    repeated, _ = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    assert child.run_id == repeated.run_id != "source"
    assert child.batch_id == "batch" and req.include_review and req.include_claim_check
    snapshot = s.repo.get_dispatch(child.run_id)["dispatch_snapshot"]
    assert snapshot["workflow_version"] == RESOURCE_RETRY_WORKFLOW_VERSION
    assert ResourceRetryContext.model_validate_json(json.dumps(snapshot["resource_retry_context"])) == context
    assert "resource_retry_context" not in s.repo.get(child.run_id).request_payload
    assert s.repo.get("source").model_dump(mode="json") == before
    assert s.resources.get("parent").model_dump(mode="json") == parent


def test_frozen_delivery_after_new_background_service_and_current_profile_change(source):
    s = source
    child, request = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    restarted = GenerationJobService(s.repo, s.generation)
    current = s.learner.model_copy(update={"learning_goal": "changed now"})
    restarted.run_job(current, request, child.run_id, child.batch_id)
    assert s.repo.get(child.run_id).job_status == "completed"
    learner, _, kwargs = s.calls[0]
    assert learner.learning_goal == "frozen goal"
    assert kwargs["resource_retry_context"]["source_run_id"] == "source"
    restarted.run_job(current, request, child.run_id, child.batch_id)
    assert len(s.calls) == 1


@pytest.mark.parametrize("damage", ["missing_context", "unknown_version", "wrong_version"])
def test_background_dispatch_corruption_never_falls_back_to_diagnosis(source, damage):
    s = source
    child, request = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    snapshot = s.repo._dispatch_metadata[child.run_id]["dispatch_snapshot"]
    if damage == "missing_context":
        snapshot.pop("resource_retry_context")
    else:
        snapshot["workflow_version"] = "unknown" if damage == "unknown_version" else "learning_documents.v1"
    s.service.run_job(s.learner, request, child.run_id)
    assert s.repo.get(child.run_id).job_status == "failed"
    assert not s.calls


def test_retry_skips_mastery_focus_and_target_reclassification(source):
    s = source
    calls = []
    class Mastery:
        def schedule_generation(self, learner, **kwargs):
            calls.append(kwargs)

        def __getattr__(self, name):
            raise AssertionError(f"retry must not recalculate {name}")
    s.service.mastery_service = Mastery()
    child, _ = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
    assert len(calls) == 1 and calls[0]["run_id"] == child.run_id


def test_failed_execution_without_draft_can_retry_as_new_resource(source):
    s = source
    record = s.resources.get_execution("source", s.spec.resource_spec_id, "text")
    s.resources.upsert_execution(record.model_copy(update={"resource_id": None}))
    assert prepare(s).source_resource is None


def test_feedback_merges_only_selected_claim_instructions_and_deduplicates(source):
    s = source
    own = {"target_resource_type": "讲义", "instruction": "repair"}
    claim = {"target_resource_type": "讲义", "target_resource_id": "parent", "instruction": "fix Claim"}
    projection = {**s.checkpoint.state_projection, "review": {
        "revision_instructions": [own, claim, {"target_resource_type": "实操指南", "instruction": "other"}],
        "issues": [{"resource_id": "parent", "message": "own"}, {"resource_id": "other", "message": "other"}]}}
    s.checkpoint = s.checkpoint.model_copy(update={"state_projection": projection, "state_hash": canonical_hash(projection)})
    feedback = prepare(s).revision_feedback
    assert feedback["revision_instructions"] == [own, claim]
    assert feedback["issues"] == [{"resource_id": "parent", "message": "own"}]


def test_missing_checkpoint_and_context_size_budget_reject(source, monkeypatch):
    s = source
    checkpoints = s.audit.list_checkpoints
    s.audit.list_checkpoints = lambda run: []
    with pytest.raises(ApplicationError) as caught:
        prepare(s)
    assert caught.value.status_code == 409
    s.audit.list_checkpoints = checkpoints
    monkeypatch.setattr("app.services.generation.resource_retry.get_settings",
                        lambda: SimpleNamespace(workflow_checkpoint_max_bytes=1))
    with pytest.raises(ApplicationError) as caught:
        prepare(s)
    assert caught.value.status_code == 409 and len(s.repo._store) == 1


@pytest.mark.parametrize("field,value", [("schema_version", "unknown"), ("context_hash", "0" * 64)])
def test_internal_context_tampering_rejected(source, field, value):
    payload = prepare(source).model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValueError):
        ResourceRetryContext.from_snapshot(payload)


@pytest.mark.parametrize("change,status", [
    ("missing_run", 404), ("other_learner", 404), ("missing_spec", 404), ("representation", 422),
    ("nonterminal", 409), ("approved", 409), ("published", 409), ("missing_dispatch", 409),
    ("bad_request_hash", 409), ("bad_checkpoint_hash", 409), ("evidence_scope", 409), ("other_owner", 409),
])
def test_prepare_rejects_without_creating_child(source, change, status):
    s = source
    args = {}
    if change == "missing_run":
        args["run_id"] = "missing"
    elif change == "other_learner":
        args["learner"] = s.learner.model_copy(update={"learner_id": "other"})
    elif change == "other_owner":
        args["learner"] = s.learner.model_copy(update={"user_id": "intruder"})
    elif change == "missing_spec":
        args["spec_id"] = str(uuid4())
    elif change == "representation":
        args["representation"] = "html"
    elif change == "nonterminal":
        s.repo._store["source"]["job_status"] = "running"
    elif change == "approved":
        record = s.resources.get_execution("source", s.spec.resource_spec_id, "text")
        s.resources.upsert_execution(record.model_copy(update={"state": "approved"}))
    elif change == "published":
        parent = s.resources.get("parent").model_copy(update={"publication_status": "published"})
        s.resources.save(parent, "learner", "retry", run_id="source", batch_id="batch")
    elif change == "missing_dispatch":
        s.repo._dispatch_metadata["source"]["dispatch_snapshot"] = None
    elif change == "bad_request_hash":
        s.repo._dispatch_metadata["source"]["dispatch_snapshot"]["request_hash"] = "0" * 64
    elif change == "bad_checkpoint_hash":
        s.checkpoint = s.checkpoint.model_copy(update={"state_hash": "0" * 64})
    elif change == "evidence_scope":
        s.evidence = s.evidence.model_copy(update={"run_id": "foreign"})
    with pytest.raises(ApplicationError) as caught:
        prepare(s, **args)
    assert caught.value.status_code == status
    assert len(s.repo._store) == 1


def test_idempotency_key_scope_and_conflicting_submission(source):
    s = source
    one, _ = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text", idempotency_key="same")
    two, _ = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text", idempotency_key="other")
    assert one.run_id != two.run_id
    projection = {**s.checkpoint.state_projection, "diagnosis": {"summary": "changed"}}
    s.checkpoint = s.checkpoint.model_copy(update={"state_projection": projection, "state_hash": canonical_hash(projection)})
    with pytest.raises(ApplicationError) as caught:
        s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text", idempotency_key="same")
    assert caught.value.status_code == 409


@pytest.mark.parametrize("mode", ["valid", "unknown_version", "missing_context", "transaction_failure"])
def test_sqlite_create_claim_and_restart_reads_persisted_context(tmp_path, monkeypatch, mode):
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'retry.db'}", connect_args={"check_same_thread": False}))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    try:
        with factory() as db:
            db.add(KnowledgeBaseORM(knowledge_base_id="kb", name="synthetic"))
            db.add(UserProfileORM(user_id="owner", display_name="synthetic", identity="test", education="本科", major="软件"))
            db.commit()
            db.add(LearnerProfileORM(learner_id="learner", user_id="owner", learner_type="test", education="本科", major="软件", learning_goal="frozen goal"))
            db.commit()
        s = source_state(SQLGenerationJobRepository(factory))
        if mode == "transaction_failure":
            original_create = SQLGenerationJobRepository.create

            def fail_after_create(repository, *args, **kwargs):
                original_create(repository, *args, **kwargs)
                raise RuntimeError("synthetic transaction failure")

            monkeypatch.setattr(SQLGenerationJobRepository, "create", fail_after_create)
            with pytest.raises(RuntimeError, match="synthetic transaction failure"):
                s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
            assert len(s.repo.list_by_learner("learner")) == 1
            assert s.repo.get("source").job_status == "completed"
            return
        child, _ = s.service.create_resource_retry(s.learner, "source", s.spec.resource_spec_id, "text")
        restarted = GenerationJobService(SQLGenerationJobRepository(factory), s.generation, dispatch_mode="worker")
        claim = restarted.job_repo.claim_next("restarted-worker", 60)
        assert claim.run_id == child.run_id
        assert claim.snapshot["workflow_version"] == RESOURCE_RETRY_WORKFLOW_VERSION
        if mode != "valid":
            snapshot = dict(claim.snapshot)
            if mode == "unknown_version":
                snapshot["workflow_version"] = "unknown"
            else:
                snapshot.pop("resource_retry_context")
            claim = replace(claim, snapshot=snapshot)
            assert restarted.run_claim(claim)
            assert restarted.job_repo.get(child.run_id).job_status == "failed"
            assert not s.calls
            return
        assert restarted.run_claim(claim)
        assert restarted.job_repo.get(child.run_id).job_status == "completed"
        assert s.calls[0][2]["resource_retry_context"]["context_hash"] == claim.snapshot["resource_retry_context"]["context_hash"]
    finally:
        engine.dispose()


def client_for(s, monkeypatch, owner="owner"):
    app = FastAPI()
    app.add_exception_handler(ApplicationError, application_exception_handler)

    @app.middleware("http")
    async def current_user(request, call_next):
        request.state.current_user = SimpleNamespace(user_id=owner)
        return await call_next(request)

    app.container = SimpleNamespace(generation_job_service=lambda: s.service,
                                    profile_service=lambda: SimpleNamespace(get=lambda ident: s.learner))
    app.include_router(api.router, prefix="/api/generate")
    scheduled = []
    monkeypatch.setattr(api, "schedule_generation", lambda *args: scheduled.append(args))
    return TestClient(app), scheduled


@pytest.mark.parametrize("owner,status", [("owner", 200), ("intruder", 404)])
def test_api_authorization_response_and_schedule(source, monkeypatch, owner, status):
    client, scheduled = client_for(source, monkeypatch, owner)
    path = f"/api/generate/jobs/source/resource-specs/{source.spec.resource_spec_id}/representations/text/retry"
    response = client.post(path, headers={"Idempotency-Key": "http"})
    assert response.status_code == status
    if status == 200:
        body = response.json()
        assert body["run_id"] != "source" and body["batch_id"] == "batch"
        assert body["learner_id"] == "learner" and body["job_status"] == "queued"
        assert len(scheduled) == 1
        assert client.post(path, headers={"Idempotency-Key": "http"}).json()["run_id"] == body["run_id"]
    else:
        assert not scheduled and len(source.repo._store) == 1


def test_api_request_body_cannot_inject_context_and_error_statuses(source, monkeypatch):
    client, scheduled = client_for(source, monkeypatch)
    path = f"/api/generate/jobs/source/resource-specs/{source.spec.resource_spec_id}/representations/text/retry"
    assert client.post(path.replace("/text/", "/html/")).status_code == 422
    assert client.post(path.replace("/source/", "/missing/")).status_code == 404
    assert client.post(path, headers={"Idempotency-Key": " "}).status_code == 422
    accepted = client.post(path, json={"resource_retry_context": {"diagnosis": "injected"}})
    assert accepted.status_code == 200
    stored = source.repo.get_dispatch(accepted.json()["run_id"])["dispatch_snapshot"]["resource_retry_context"]
    assert stored["diagnosis"] == {"summary": "frozen diagnosis"}
    scheduled.clear()
    source.repo._dispatch_metadata["source"]["dispatch_snapshot"] = None
    response = client.post(path, json={"resource_retry_context": {"learner": "injected"}})
    assert response.status_code == 409 and not scheduled
