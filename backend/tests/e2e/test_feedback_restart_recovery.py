from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.orm import sessionmaker

from app.core.security.errors import ErrorCode
from app.db.shared.database import configure_sqlite_foreign_keys
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.shared.models import (
    Base,
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    KnowledgeBaseORM,
    KnowledgeStateMutationORM,
    KnowledgeStateORM,
    LearnerProfileVersionORM,
    LearningAttemptORM,
    LearningPathMutationORM,
    LearningPathORM,
    RagSkillNodeORM,
)
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.models.feedback.feedback_loop import FeedbackFollowupSelection, KnowledgePointAttemptResult, LearningAttemptSubmit
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService


class _NoopGenerationService:
    pass


def _setup(tmp_path):
    from sqlalchemy import create_engine

    engine = configure_sqlite_foreign_keys(
        create_engine(f"sqlite:///{tmp_path / 'feedback-recovery.db'}")
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(KnowledgeBaseORM(
            knowledge_base_id="kb",
            name="Feedback recovery KB",
            version="1.0",
        ))
        db.add(RagSkillNodeORM(
            node_id="skill-a",
            knowledge_base_id="kb",
            name="Skill A",
            level="beginner",
        ))
        db.commit()
    learners = SQLLearnerRepository(factory)
    learners.save(LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="kb",
        learning_goal="闭环",
    ))
    resources = SQLResourceRepository(factory)
    resources.save(LearningResource(
        resource_id="resource",
        learner_id="learner",
        topic="检索",
        resource_type="测试题",
        difficulty="初级",
        content_text="测试",
        knowledge_points=["skill-a"],
        source_refs=[],
        publication_status="published",
    ), "learner", "检索")
    loop = SQLFeedbackLoopRepository(factory)
    jobs = SQLGenerationJobRepository(factory)
    service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=loop,
        generation_job_service=GenerationJobService(jobs, _NoopGenerationService()),
    )
    return engine, factory, learners, resources, loop, jobs, service


def _request():
    return LearningAttemptSubmit(
        learner_id="learner",
        source_resource_id="resource",
        source_resource_version=1,
        idempotency_key="restart-recovery-key",
        expected_profile_version=1,
        submitted_at=datetime(2026, 8, 15, tzinfo=timezone.utc),
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q1"],
            correct_count=4,
            total_count=10,
        )],
    )


def test_feedback_transaction_rolls_back_all_facts_before_commit(tmp_path):
    _, factory, learners, resources, _, _, service = _setup(tmp_path)

    def fail_commit(_session):
        raise RuntimeError("injected-before-commit")

    event.listen(factory.class_, "before_commit", fail_commit)
    try:
        with pytest.raises(RuntimeError, match="injected-before-commit"):
            service.process_learning_attempt(
                learners.get("learner"),
                resources.get("resource"),
                _request(),
            )
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)

    with factory() as db:
        assert db.query(LearningAttemptORM).count() == 0
        assert db.query(FeedbackDecisionORM).count() == 0
        assert db.query(KnowledgeStateORM).count() == 0
        assert db.query(KnowledgeStateMutationORM).count() == 0
        assert db.query(LearnerProfileVersionORM).count() == 0
        assert db.query(LearningPathORM).count() == 0
        assert db.query(LearningPathMutationORM).count() == 0
        assert db.query(FeedbackFollowUpRunORM).count() == 0
    assert learners.get("learner").profile_version == 1


def test_restart_reconciles_commit_to_followup_crash_window(tmp_path, monkeypatch):
    _, _, learners, resources, loop, jobs, service = _setup(tmp_path)

    result = service.process_learning_attempt(
        learners.get("learner"),
        resources.get("resource"),
        _request(),
    )

    persisted = loop.get_by_idempotency_key("learner", "restart-recovery-key")
    assert persisted is not None
    assert persisted.profile_version == 2
    assert persisted.followup_generation_status.value == "not_requested"

    assert loop.reconcile_incomplete_followups(
        stale_child_run_ids=[],
        error_code=ErrorCode.GENERATION_JOB_INTERRUPTED.value,
    ) == 0
    reconciled = loop.get_by_idempotency_key("learner", "restart-recovery-key")
    assert reconciled.followup_generation_status.value == "not_requested"
    assert reconciled.followup_error_code is None

    restarted = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=loop,
        generation_job_service=GenerationJobService(jobs, _NoopGenerationService()),
    )
    scheduled = []
    replay = restarted.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner", attempt_id=result.attempt.attempt_id, option_id="remediate-core",
        ),
        schedule_followup=lambda learner, request, run_id: scheduled.append(run_id),
    )
    assert replay.idempotent_replay is False
    assert replay.followup_generation_status.value == "queued"
    assert jobs.get(replay.followup_run_id).job_status == "queued"
    assert scheduled == [replay.followup_run_id]


def test_restart_fails_stale_job_and_idempotent_replay_requeues_it(tmp_path):
    _, _, learners, resources, loop, jobs, service = _setup(tmp_path)
    result = service.process_learning_attempt(
        learners.get("learner"),
        resources.get("resource"),
        _request(),
    )
    assert result.followup_generation_status.value == "not_requested"

    result = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner", attempt_id=result.attempt.attempt_id, option_id="remediate-core",
        ),
    )
    assert result.followup_generation_status.value == "queued"
    assert jobs.get(result.followup_run_id).job_status == "queued"

    stale_ids = jobs.fail_incomplete_before(
        datetime.now(timezone.utc) + timedelta(seconds=1),
        ErrorCode.GENERATION_JOB_INTERRUPTED.value,
    )
    assert stale_ids == [result.followup_run_id]
    assert loop.reconcile_incomplete_followups(
        stale_child_run_ids=stale_ids,
        error_code=ErrorCode.GENERATION_JOB_INTERRUPTED.value,
    ) == 1
    assert jobs.get(result.followup_run_id).job_status == "failed"
    failed = loop.get_by_idempotency_key("learner", "restart-recovery-key")
    assert failed.followup_generation_status.value == "failed"

    restarted = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=loop,
        generation_job_service=GenerationJobService(jobs, _NoopGenerationService()),
    )
    replay = restarted.process_learning_attempt(
        learners.get("learner"),
        resources.get("resource"),
        _request(),
    )
    assert replay.idempotent_replay is True
    assert replay.followup_run_id == result.followup_run_id
    assert replay.followup_generation_status.value == "failed"
    assert jobs.get(result.followup_run_id).job_status == "failed"
    replayed_selection = restarted.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner", attempt_id=result.attempt.attempt_id, option_id="remediate-core",
        ),
    )
    assert replayed_selection.followup_generation_status.value == "queued"
    assert jobs.get(result.followup_run_id).job_status == "queued"
    assert len(jobs.list_by_learner("learner")) == 1
