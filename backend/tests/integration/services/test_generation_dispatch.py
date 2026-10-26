"""Durable intent, lease reconciliation and stale execution transaction checks."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.api.generation import generation as api
from app.core.execution import ExecutionFence, execution_fence
from app.core.security.errors import ApplicationError
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.generation.fencing import ExecutionLeaseLost
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, AgentRunORM, GenerationJobORM, LearnerProfileORM, UserProfileORM
from app.main import application_exception_handler
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.persistence import BeginStepCommand, CompleteStepCommand, CreateRunCommand, WorkflowEventType, canonical_hash
from app.services.generation.dispatch import submission_identity
from app.services.generation.jobs import GenerationJobService
from app.services.generation.worker import GenerationWorker


@pytest.fixture
def state(tmp_path):
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{tmp_path / 'jobs.db'}", connect_args={"check_same_thread": False}))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        db.add(UserProfileORM(user_id="owner", display_name="synthetic", identity="test", education="本科", major="软件"))
        db.commit()
        db.add(LearnerProfileORM(learner_id="learner", user_id="owner", learner_type="test", education="本科", major="软件", learning_goal="test"))
        db.commit()
    learner = LearnerProfile(learner_id="learner", user_id="owner", learner_type="test", education="本科", major="软件", learning_goal="test")
    repo = SQLGenerationJobRepository(factory)
    audit = SQLAuditRepository(factory)
    service = GenerationJobService(repo, SimpleNamespace(audit_repo=audit), dispatch_mode="worker")
    req = GenerateRequest(learner_id="learner", topic="durable", profile_focus_mode="off", resource_types=["讲义"], include_review=False)
    yield SimpleNamespace(engine=engine, factory=factory, repo=repo, audit=audit, service=service, learner=learner, req=req)
    engine.dispose()


def start_run(s, claim, *, expired=False):
    now = datetime.now(timezone.utc)
    lease = now + timedelta(seconds=-1 if expired else 60)
    s.audit.create_run(CreateRunCommand(run_id=claim.run_id, learner_id="learner", request_snapshot={},
                       request_hash=canonical_hash({}), owner_instance_id=claim.owner, lease_expires_at=lease))
    s.audit.start_run(claim.run_id, occurred_at=now, lease_expires_at=lease)


def test_atomic_claim_and_prestart_recovery(state):
    s = state
    job = s.service.create_job(s.learner, s.req)
    with ThreadPoolExecutor(2) as pool:
        claims = list(pool.map(lambda owner: s.repo.claim_next(owner, 60), ["one", "two"]))
    first = next(claim for claim in claims if claim)
    assert sum(claim is not None for claim in claims) == 1
    assert s.repo.get(job.run_id).job_status == "running"
    later = datetime.now(timezone.utc) + timedelta(seconds=61)
    assert s.repo.reconcile(now=later)["requeued"] == 1
    second = s.repo.claim_next("replacement", 60, now=later + timedelta(seconds=5))
    assert second.run_id == first.run_id and second.epoch > first.epoch
    assert not s.repo.finish_claim(first, resource_ids=["late"])
    assert not s.repo.renew_claim(first, 60)


def test_prestart_recovery_exhausts_three_claims_and_stops(state):
    s = state
    job = s.service.create_job(s.learner, s.req)
    now = datetime.now(timezone.utc)
    for attempt in range(1, 4):
        claim = s.repo.claim_next(f"worker-{attempt}", 30, now=now)
        assert claim.claim_count == attempt
        later = now + timedelta(seconds=31)
        result = s.repo.reconcile(now=later)
        assert result["requeued"] == (1 if attempt < 3 else 0)
        now = later + timedelta(seconds=10)
    assert s.repo.get(job.run_id).job_status == "failed"
    assert s.repo.claim_next("fourth", 30, now=now) is None


def test_effective_run_lease_wins_over_created_age(state):
    s = state
    job = s.service.create_job(s.learner, s.req)
    claim = s.repo.claim_next("owner", 60)
    start_run(s, claim)
    with s.factory() as db:
        db.get(GenerationJobORM, job.run_id).created_at = datetime.now(timezone.utc) - timedelta(seconds=2000)
        db.commit()
    assert s.repo.reconcile()["failed_run_ids"] == []
    assert s.repo.get(job.run_id).job_status == "running"
    assert s.audit.get_run(job.run_id).status.value == "running"
    # The same reconciler observes expiry on a later periodic poll.
    assert s.repo.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=61))["failed_run_ids"] == [job.run_id]
    assert s.audit.get_run(job.run_id).status.value == "interrupted"
    assert len([e for e in s.audit.list_events(job.run_id) if e.event_type == WorkflowEventType.RUN_INTERRUPTED]) == 1
    assert s.repo.reconcile(now=datetime.now(timezone.utc) + timedelta(seconds=62))["failed_run_ids"] == []


def test_stale_observation_cannot_override_renewal(state):
    s = state
    s.service.create_job(s.learner, s.req)
    claim = s.repo.claim_next("owner", 60)
    start_run(s, claim, expired=True)
    with s.factory() as observer:
        observed = observer.get(AgentRunORM, claim.run_id)
        assert s.repo.renew_claim(claim, 120)
        assert not s.audit.interrupt_expired_in_session(observer, observed, datetime.now(timezone.utc))
        observer.commit()
    assert s.audit.get_run(claim.run_id).status.value == "running"


def test_late_executor_cannot_publish_event_checkpoint_or_terminal(state):
    s = state
    s.service.create_job(s.learner, s.req)
    claim = s.repo.claim_next("owner", 60)
    with execution_fence(ExecutionFence(claim.run_id, claim.owner, claim.epoch)):
        start_run(s, claim)
        s.audit.begin_step(BeginStepCommand(run_id=claim.run_id, step_id="synthetic-step", step_sequence=1,
                                           node_name="node", agent_name="node", action="synthetic"))
        s.audit.complete_step(CompleteStepCommand(run_id=claim.run_id, step_id="synthetic-step", trace={"status": "success"}))
    # Expire the actual persisted run and claim; no process or user data is involved.
    with s.factory() as db:
        expired = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.get(GenerationJobORM, claim.run_id).lease_expires_at = expired
        db.get(AgentRunORM, claim.run_id).lease_expires_at = expired
        db.commit()
    s.repo.reconcile()
    before = len(s.audit.list_events(claim.run_id))
    with execution_fence(ExecutionFence(claim.run_id, claim.owner, claim.epoch)):
        with pytest.raises(ExecutionLeaseLost):
            s.audit.append_event(claim.run_id, WorkflowEventType.RESOURCE_PERSISTED, payload={}, occurred_at=datetime.now(timezone.utc))
        with pytest.raises(ExecutionLeaseLost):
            SQLResourceRepository(s.factory).save(LearningResource(resource_id="late", resource_type="讲义", difficulty="初级", content_text="synthetic", knowledge_points=[], source_refs=[], publication_status="published"), "learner", "durable", run_id=claim.run_id)
        # A checkpoint failure also rolls back its associated event.
        with pytest.raises(ExecutionLeaseLost):
            s.audit.save_checkpoint(run_id=claim.run_id, step_id="synthetic-step", step_sequence=1, node_name="node",
                                    state_projection={}, state_hash=canonical_hash({}), occurred_at=datetime.now(timezone.utc))
    assert not s.repo.finish_claim(claim, resource_ids=["late"])
    assert SQLResourceRepository(s.factory).get("late") is None
    assert len(s.audit.list_events(claim.run_id)) == before
    assert s.repo.get(claim.run_id).job_status == "failed"


def test_terminal_retry_is_a_unique_new_attempt(state):
    s = state
    original = s.service.create_job(s.learner, s.req, run_id="original")
    claim = s.repo.claim_next("owner", 60)
    start_run(s, claim, expired=True)
    s.repo.reconcile()
    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: s.service.create_job(s.learner, s.req, run_id=original.run_id, retry_failed=True), range(2)))
    assert results[0].run_id == results[1].run_id != original.run_id
    assert s.repo.get(original.run_id).superseded_by_run_id == results[0].run_id
    assert s.audit.get_run(original.run_id).status.value == "interrupted"
    assert s.repo.get(original.run_id).job_status == "failed"
    next_claim = s.repo.claim_next("next", 60)
    assert s.repo.finish_claim(next_claim, error_code="synthetic")
    third = s.service.create_job(s.learner, s.req, run_id=original.run_id, retry_failed=True)
    assert third.run_id != next_claim.run_id
    assert s.repo.get(next_claim.run_id).superseded_by_run_id == third.run_id


def test_api_only_persists_and_enforces_submission_key(state, monkeypatch):
    s = state
    app = FastAPI()
    app.add_exception_handler(ApplicationError, application_exception_handler)
    app.container = SimpleNamespace(profile_service=lambda: SimpleNamespace(get=lambda _: s.learner), generation_job_service=lambda: s.service)
    app.include_router(api.router, prefix="/api/generate")
    monkeypatch.setattr(api, "build_health_report", lambda _: SimpleNamespace(status="ready", error_codes=[]))
    with TestClient(app) as client:
        body = s.req.model_dump(mode="json")
        one = client.post("/api/generate/jobs", json=body, headers={"Idempotency-Key": "submission"})
        two = client.post("/api/generate/jobs", json=body, headers={"Idempotency-Key": "submission"})
        assert one.status_code == two.status_code == 200
        assert one.json()["run_id"] == two.json()["run_id"]
        assert s.repo.get(one.json()["run_id"]).job_status == "queued"
        assert client.post("/api/generate/jobs", json={**body, "topic": "other"}, headers={"Idempotency-Key": "submission"}).status_code == 409
        assert client.post("/api/generate/jobs", json=body, headers={"Idempotency-Key": "x" * 129}).status_code == 422
        other = s.learner.model_copy(update={"user_id": "another"})
        assert submission_identity(s.learner, s.req, "submission", "generation")["run_id"] != submission_identity(other, s.req, "submission", "generation")["run_id"]


def test_worker_reconciles_without_blocking_heartbeat(state):
    s = state
    s.service.create_job(s.learner, s.req)
    def service():
        return SimpleNamespace(run_claim=lambda claim: s.repo.finish_claim(claim, resource_ids=[]))
    feedback = SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0)
    worker = GenerationWorker(s.repo, feedback, service, poll_seconds=0.01)
    assert worker.run_once() == {"claimed": 1, "processed": 1, "failed": 0}
    assert worker.health_snapshot()["ready"]
    worker.stop()
    assert worker.run_once()["claimed"] == 0


def test_invalid_frozen_version_fails_before_execution(state):
    s = state
    job = s.service.create_job(s.learner, s.req)
    with s.factory() as db:
        row = db.get(GenerationJobORM, job.run_id)
        row.dispatch_snapshot = {**row.dispatch_snapshot, "workflow_version": "unsupported"}
        db.commit()
    claim = s.repo.claim_next("owner", 60)
    assert s.service.run_claim(claim)
    assert s.repo.get(job.run_id).job_status == "failed"
    assert s.audit.get_run(job.run_id) is None


def test_legacy_failed_job_can_retry_as_a_new_frozen_attempt(state):
    s = state
    s.repo.create("legacy", s.learner.learner_id, s.req.topic, None, s.req.model_dump(mode="json"))
    s.repo.mark_failed("legacy", "synthetic-interruption")
    retry = s.service.create_job(s.learner, s.req, run_id="legacy", retry_failed=True, submission_hash="a" * 64)
    assert retry.run_id != "legacy"
    assert s.repo.get("legacy").job_status == "failed"
    assert s.repo.get_dispatch(retry.run_id)["dispatch_mode"] == "worker"


def test_memory_submission_replay_does_not_execute_completed_job_again(state):
    from app.db.generation.memory import MemoryGenerationJobRepository
    s = state
    calls = []
    def generate(*args, **kwargs):
        calls.append(kwargs["run_id"])
        return SimpleNamespace(resources=[])
    repo = MemoryGenerationJobRepository()
    service = GenerationJobService(repo, SimpleNamespace(generate_with_run_id=generate))
    identity = submission_identity(s.learner, s.req, "memory-submit", "generation")
    job = service.create_job(s.learner, s.req, **identity)
    with ThreadPoolExecutor(2) as pool:
        list(pool.map(lambda _: service.run_job(s.learner, s.req, job.run_id), range(2)))
    replay = service.create_job(s.learner, s.req, **identity)
    service.run_job(s.learner, s.req, replay.run_id)
    assert calls == [job.run_id]
    assert repo.get(job.run_id).job_status == "completed"


@pytest.mark.parametrize("worker_claim", [False, True])
def test_fence_allows_owned_terminal_transition_with_autoflush(state, worker_claim):
    from app.models.shared.persistence import RunStatus
    s = state
    audit = SQLAuditRepository(sessionmaker(bind=s.engine, autoflush=True))
    job = s.service.create_job(s.learner, s.req)
    claim = s.repo.claim_next("owner", 60)
    fence = ExecutionFence(claim.run_id, claim.owner, claim.epoch if worker_claim else None)
    with execution_fence(fence):
        start_run(s, claim)
        audit.mark_finalizing(claim.run_id, workflow_status="completed", current_node="done",
            generation_attempt=1, revision_count=0, retrieval_status="ready", final_decision="approve",
            occurred_at=datetime.now(timezone.utc))
        audit.complete_run(claim.run_id, status=RunStatus.COMPLETED, workflow_status="completed",
            execution_status="success", final_decision="approve", occurred_at=datetime.now(timezone.utc))
        with pytest.raises(ExecutionLeaseLost):
            audit.append_event(claim.run_id, WorkflowEventType.RUN_STARTED, payload={}, occurred_at=datetime.now(timezone.utc))
    assert s.audit.get_run(job.run_id).status == RunStatus.COMPLETED
    assert s.repo.finish_claim(claim, error_code="synthetic-response-failure")
    assert s.repo.get(job.run_id).job_status == "completed"


def test_periodic_reconciliation_repairs_curriculum_crash_window(state):
    from app.db.learners.curriculum import SQLCurriculumRepository
    from app.db.shared.models import KnowledgeBaseORM, LearnerCurriculumNodeORM, RagSkillNodeORM
    from app.services.generation.reconciliation import GenerationReconciler
    s = state
    job = s.service.create_job(s.learner, s.req)
    s.repo.mark_failed(job.run_id, "synthetic-interruption")
    with s.factory() as db:
        db.add(KnowledgeBaseORM(knowledge_base_id="kb", name="synthetic", version="1"))
        db.commit()
        for identity in ("stale", "newer"):
            db.add(RagSkillNodeORM(node_id=identity, knowledge_base_id="kb", name=identity, level="beginner"))
        db.commit()
        for identity, owner in [("stale", job.run_id), ("newer", "new-run")]:
            db.add(LearnerCurriculumNodeORM(curriculum_node_id=identity, learner_id="learner",
                knowledge_base_id="kb", skill_node_id=identity, scheduled_run_id=owner,
                progress_status="scheduled", published_resource_count=0))
        db.commit()
    reconciler = GenerationReconciler(s.repo, SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
                                     curriculum=SQLCurriculumRepository(s.factory))
    assert reconciler.run_once()["curriculum"] == 1
    assert reconciler.run_once()["curriculum"] == 0
    with s.factory() as db:
        assert db.get(LearnerCurriculumNodeORM, "stale").progress_status == "unplanned"
        assert db.get(LearnerCurriculumNodeORM, "newer").scheduled_run_id == "new-run"
