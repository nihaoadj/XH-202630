"""File-backed restarts: round facts, queued dispatch, leases and retry bindings.

These are deterministic local fault injections.  They reopen a real SQLite file
and rebuild every repository, but never contact a model or a real worker
process; a synthetic generation result stands in for long-running workflows.
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository
from app.db.feedback.sql_repository import SQLFeedbackRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learners.curriculum import SQLCurriculumRepository
from app.db.learners.mastery import SQLMasteryRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.learners.tier_progress import SQLTierProgressRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.shared.models import Base, GenerationJobORM, KnowledgeBaseORM, RagSkillNodeORM
from app.models.feedback.rounds import GenerateRoundCreateRequestV1
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, SkillNode
from app.services.feedback.feedback import FeedbackService
from app.services.feedback.round_learning import RoundLearningService
from app.services.feedback.round_uow import RoundUnitOfWork
from app.services.generation.jobs import GenerationJobService
from app.services.generation.round_continuations import create_bound_job
from app.services.generation.worker import GenerationWorker
from app.services.learners.mastery import MasteryService

pytestmark = pytest.mark.e2e

NODES = ("a", "b")


class SyntheticGeneration:
    """Minimal stand-in for the resource workflow; records every execution."""

    def __init__(self, calls=None, failure=None, fail_run_ids=()):
        self.calls = calls if calls is not None else []
        self.failure = failure
        self.fail_run_ids = set(fail_run_ids)

    def generate_with_run_id(self, learner, request, *, run_id, batch_id=None, **kwargs):
        self.calls.append(run_id)
        if self.failure is not None:
            raise self.failure
        if run_id in self.fail_run_ids:
            raise RuntimeError(f"synthetic member failure: {run_id}")
        return SimpleNamespace(resources=[], workflow_status="completed")


def open_round_db(path, *, dispatch_mode="background", generation=None):
    """Construct a complete round service graph on one SQLite file."""
    engine = configure_sqlite_foreign_keys(create_engine(f"sqlite:///{path}"))
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False)
    with factory() as db:
        if db.get(KnowledgeBaseORM, "kb") is None:
            db.add(KnowledgeBaseORM(knowledge_base_id="kb", name="fixture"))
            db.commit()
            db.add_all(
                RagSkillNodeORM(node_id=key, knowledge_base_id="kb", name=key, tier=1)
                for key in NODES
            )
            db.commit()

    learners = SQLLearnerRepository(factory)
    profile = LearnerProfile(
        learner_id="learner", learner_type="test", education="test", major="test",
        knowledge_base_id="kb", learning_goal="test",
    )
    if learners.get("learner") is None:
        learners.save(profile)

    resources = SQLResourceRepository(factory)
    skill_nodes = [SkillNode(node_id=key, knowledge_base_id="kb", name=key, tier=1) for key in NODES]
    knowledge = SimpleNamespace(
        list_skill_nodes=lambda *_: skill_nodes,
        load_assessment_questions=lambda *_: [],
        load_diagnostic_questions=lambda *_: [],
        select_diagnostic_questions=lambda *args, **kwargs: [],
    )
    mastery = MasteryService(
        SQLMasteryRepository(factory), knowledge, resource_repo=resources,
        curriculum_repo=SQLCurriculumRepository(factory),
        tier_progress_repo=SQLTierProgressRepository(factory),
    )
    rounds = SQLRoundRepository(factory)
    generation = generation or SyntheticGeneration()
    jobs = GenerationJobService(
        SQLGenerationJobRepository(factory), generation, mastery,
        dispatch_mode=dispatch_mode, round_repository=rounds,
    )
    feedback = FeedbackService(
        SQLFeedbackRepository(factory), SQLFeedbackLoopRepository(factory), jobs,
        mastery_service=mastery, resource_repo=resources,
    )
    service = RoundLearningService(
        rounds, feedback, learners, Settings(learning_round_creation_enabled=True),
    )
    return SimpleNamespace(
        engine=engine, factory=factory, learners=learners, resources=resources,
        mastery=mastery, rounds=rounds, jobs=jobs, feedback=feedback,
        service=service, generation=generation,
    )


def create_payload(key="round-restart", node="a"):
    return GenerateRoundCreateRequestV1(
        learner_id="learner", topic=node, knowledge_base_id="kb",
        target_skill_nodes=[node], resource_types=["讲义"], selection_key=key,
    )


def round_uow(db):
    return RoundUnitOfWork(db.rounds, db.feedback, db.learners)


def run_worker(db):
    worker = GenerationWorker(
        db.jobs.job_repo,
        SimpleNamespace(reconcile_incomplete_followups=lambda **_: 0),
        lambda: db.jobs, lease_seconds=60, poll_seconds=0.01,
    )
    return worker.run_once()


def only_binding(db, run_id):
    return db.rounds.one("learning_round_job_bindings", run_id=run_id)


def test_round_creation_replay_after_reopen_writes_nothing_new(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path)
    profile = first.learners.get("learner")
    created = first.service.create(profile, create_payload())
    run_ids = [member.job_ids[0] for member in created.members]
    version = profile.profile_version
    first.engine.dispose()

    reopened = open_round_db(path)
    replayed = reopened.service._create_round(
        reopened.learners.get("learner"), "round-restart",
        create_payload().model_dump(mode="json"), "a", ["讲义"], False,
    )

    assert replayed.model_dump() == created.model_dump()
    assert len(reopened.rounds.find("learning_rounds")) == 1
    assert len(reopened.rounds.find("learning_round_job_bindings")) == 1
    assert reopened.learners.get("learner").profile_version == version
    assert reopened.jobs.job_repo.get(run_ids[0]).job_status == "queued"
    reopened.engine.dispose()


def test_queued_round_job_runs_once_after_restart_with_frozen_scope(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    created = first.service.create(first.learners.get("learner"), create_payload())
    run_id = created.members[0].job_ids[0]
    dispatch = first.jobs.job_repo.get_dispatch(run_id)
    assert dispatch["dispatch_mode"] == "worker"
    assert dispatch["dispatch_snapshot"]["learner"]["learner_id"] == "learner"
    version = first.learners.get("learner").profile_version
    first.engine.dispose()

    reopened = open_round_db(path, dispatch_mode="worker")
    outcome = run_worker(reopened)

    assert outcome == {"claimed": 1, "processed": 1, "failed": 0}
    assert reopened.generation.calls == [run_id]
    assert reopened.jobs.job_repo.get(run_id).job_status == "completed"
    binding = only_binding(reopened, run_id)
    assert binding["relation_kind"] == "production"
    stage_node = reopened.rounds.one("learning_round_stage_nodes", stage_node_id=binding["stage_node_id"])
    assert stage_node["recovery_count"] == 0
    assert reopened.learners.get("learner").profile_version == version
    # The binding is stable across a second poll; the same Run cannot execute twice.
    assert run_worker(reopened)["claimed"] == 0
    assert reopened.generation.calls == [run_id]
    reopened.engine.dispose()


def test_abandoned_worker_claim_is_reclaimed_after_restart(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    created = first.service.create(first.learners.get("learner"), create_payload())
    run_id = created.members[0].job_ids[0]
    assert first.jobs.job_repo.claim_next("crashed-worker", 60) is not None
    first.engine.dispose()

    reopened = open_round_db(path, dispatch_mode="worker")
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    with reopened.factory() as db:
        row = db.get(GenerationJobORM, run_id)
        row.lease_expires_at = past
        row.next_attempt_at = past
        db.commit()
    assert reopened.jobs.job_repo.reconcile()["requeued"] == 1
    # Requeue applies a short backoff; the next worker poll must not wait for it.
    with reopened.factory() as db:
        db.get(GenerationJobORM, run_id).next_attempt_at = past
        db.commit()

    outcome = run_worker(reopened)

    assert outcome == {"claimed": 1, "processed": 1, "failed": 0}
    assert reopened.generation.calls == [run_id]
    assert reopened.jobs.job_repo.get(run_id).job_status == "completed"
    reopened.engine.dispose()


def test_failed_round_job_retry_keeps_the_same_stage_node_binding(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    created = first.service.create(first.learners.get("learner"), create_payload())
    source_run = created.members[0].job_ids[0]
    first.engine.dispose()

    failing = open_round_db(path, dispatch_mode="worker", generation=SyntheticGeneration(failure=RuntimeError("synthetic failure")))
    assert run_worker(failing)["failed"] == 1
    assert failing.jobs.job_repo.get(source_run).job_status == "failed"
    binding = only_binding(failing, source_run)
    source_job = failing.jobs.job_repo.get(source_run)
    request = GenerateRequest.model_validate(source_job.request_payload)

    retry_run = "retry-run-1"
    created_retry, frozen = create_bound_job(
        failing.jobs, failing.learners.get("learner"), binding, request, retry_run,
        "retry-submission-hash", relation="retry", source_run_id=source_run,
        round_uow_factory=lambda: round_uow(failing),
    )
    replay, _ = create_bound_job(
        failing.jobs, failing.learners.get("learner"), binding, request, retry_run,
        "retry-submission-hash", relation="retry", source_run_id=source_run,
        round_uow_factory=lambda: round_uow(failing),
    )

    assert created_retry.run_id == retry_run == replay.run_id
    assert frozen.target_skill_nodes == ["a"]
    retry_binding = only_binding(failing, retry_run)
    assert retry_binding["stage_node_id"] == binding["stage_node_id"]
    assert retry_binding["relation_kind"] == "retry"
    assert retry_binding["source_run_id"] == source_run
    stage_node = failing.rounds.one("learning_round_stage_nodes", stage_node_id=binding["stage_node_id"])
    assert stage_node["recovery_count"] == 1
    assert stage_node["budget_counters"]["resource_recoveries"] == {"讲义": 1}
    assert len(failing.rounds.find("learning_round_job_bindings")) == 2
    failed_job = failing.jobs.job_repo.get(source_run)
    assert failed_job.job_status == "failed"
    failing.engine.dispose()

    reopened = open_round_db(path, dispatch_mode="worker")
    outcome = run_worker(reopened)

    assert outcome["claimed"] == 1 and outcome["processed"] == 1
    assert reopened.generation.calls == [retry_run]
    assert reopened.jobs.job_repo.get(retry_run).job_status == "completed"
    assert reopened.jobs.job_repo.get(source_run).job_status == "failed"
    assert len(reopened.rounds.find("learning_round_job_bindings")) == 2
    assert len(reopened.rounds.find("learning_rounds")) == 1
    reopened.engine.dispose()


def test_unbound_legacy_dual_node_job_still_recovers_after_round_schema_exists(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    profile = first.learners.get("learner")
    job = first.jobs.create_job(
        profile,
        GenerateRequest(
            learner_id="learner", knowledge_base_id="kb", topic="legacy",
            target_skill_nodes=["a", "b"], resource_types=["分阶测试题"],
            difficulty_preference="初级", include_review=True,
        ),
        run_id="legacy-worker-run", batch_id="legacy-worker-batch",
        submission_hash="legacy-worker-submission",
    )
    assert job.run_id == "legacy-worker-run"
    assert first.rounds.find("learning_rounds") == []
    first.engine.dispose()

    reopened = open_round_db(path, dispatch_mode="worker")
    outcome = run_worker(reopened)

    assert outcome == {"claimed": 1, "processed": 1, "failed": 0}
    assert reopened.generation.calls == ["legacy-worker-run"]
    assert reopened.jobs.job_repo.get("legacy-worker-run").job_status == "completed"
    assert reopened.jobs.get_job("legacy-worker-run").round_binding is None
    assert reopened.rounds.find("learning_rounds") == []
    assert reopened.rounds.find("learning_round_job_bindings") == []
    reopened.engine.dispose()


def test_expired_owner_cannot_finish_after_a_new_claim_takes_over(tmp_path):
    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    created = first.service.create(first.learners.get("learner"), create_payload())
    run_id = created.members[0].job_ids[0]
    stale = first.jobs.job_repo.claim_next("owner-old", 60)
    assert stale is not None
    first.engine.dispose()

    reopened = open_round_db(path, dispatch_mode="worker")
    past = datetime.now(timezone.utc) - timedelta(seconds=10)
    with reopened.factory() as db:
        row = db.get(GenerationJobORM, run_id)
        row.lease_expires_at = past
        row.next_attempt_at = past
        db.commit()
    assert reopened.jobs.job_repo.reconcile()["requeued"] == 1
    with reopened.factory() as db:
        db.get(GenerationJobORM, run_id).next_attempt_at = past
        db.commit()

    current = reopened.jobs.job_repo.claim_next("owner-new", 60)
    assert current is not None and current.owner == "owner-new"
    assert reopened.jobs.job_repo.finish_claim(stale, resource_ids=[]) is False
    assert reopened.jobs.job_repo.get(run_id).job_status == "running"
    assert reopened.jobs.job_repo.finish_claim(current, resource_ids=[]) is True
    assert reopened.jobs.job_repo.get(run_id).job_status == "completed"
    # The binding is not duplicated by a lease takeover.
    assert len(reopened.rounds.find("learning_round_job_bindings")) == 1
    reopened.engine.dispose()


def test_one_failed_member_retry_does_not_rebind_the_successful_member(tmp_path):
    from tests.integration.services.test_round_generation import publish, submit

    path = tmp_path / "rounds.db"
    first = open_round_db(path, dispatch_mode="worker")
    profile = first.learners.get("learner")
    source = first.service.create(profile, create_payload("member-source"))
    publish(first.service, source)
    submit(first.service, profile, source, "member-source-submit")
    first.jobs.job_repo.mark_completed(source.members[0].job_ids[0], [])
    result = first.service._create_round(
        first.learners.get("learner"), "member-retry-round", {"fixture": "member-retry"},
        "b", ["讲义"], False, review_node_id="a",
    )
    primary = next(member for member in result.members if member.role == "primary")
    review = next(member for member in result.members if member.role == "review")
    first.engine.dispose()

    reopened = open_round_db(
        path, dispatch_mode="worker",
        generation=SyntheticGeneration(fail_run_ids={review.job_ids[0]}),
    )
    for _ in range(3):
        run_worker(reopened)

    assert reopened.jobs.job_repo.get(primary.job_ids[0]).job_status == "completed"
    assert reopened.jobs.job_repo.get(review.job_ids[0]).job_status == "failed"
    review_binding = only_binding(reopened, review.job_ids[0])
    failed_request = GenerateRequest.model_validate(
        reopened.jobs.job_repo.get(review.job_ids[0]).request_payload)
    retry_run = "review-retry-run"

    created, _ = create_bound_job(
        reopened.jobs, reopened.learners.get("learner"), review_binding, failed_request, retry_run,
        "review-retry-hash", relation="retry", source_run_id=review.job_ids[0],
        round_uow_factory=lambda: round_uow(reopened),
    )
    assert created.run_id == retry_run
    assert only_binding(reopened, primary.job_ids[0])["relation_kind"] == "production"
    assert only_binding(reopened, review.job_ids[0])["relation_kind"] == "production"
    assert only_binding(reopened, retry_run)["stage_node_id"] == review_binding["stage_node_id"]
    assert len(reopened.rounds.find("learning_round_job_bindings")) == 4
    reopened.engine.dispose()

    final = open_round_db(path, dispatch_mode="worker")
    for _ in range(2):
        run_worker(final)
    assert final.generation.calls == [retry_run]
    assert final.jobs.job_repo.get(retry_run).job_status == "completed"
    assert final.jobs.job_repo.get(primary.job_ids[0]).job_status == "completed"
    assert final.jobs.job_repo.get(review.job_ids[0]).job_status == "failed"
    assert len(final.rounds.find("learning_round_job_bindings")) == 4
    final.engine.dispose()
