"""Fault injection for the continuation task/lineage transaction boundary."""

from copy import deepcopy
from datetime import UTC, datetime
from threading import Event, Thread
from types import SimpleNamespace

import pytest
from app.api.learning_documents import documents
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learners.curriculum import (
    MemoryCurriculumRepository,
    SQLCurriculumRepository,
)
from app.db.learners.mastery import MemoryMasteryRepository, SQLMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import (
    MemoryTierProgressRepository,
    SQLTierProgressRepository,
)
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.db.shared.models import (
    AbilityStateEventORM,
    AgentRunORM,
    Base,
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    GeneratedResourceORM,
    GenerationJobORM,
    KnowledgeStateORM,
    LearnerCurriculumNodeORM,
    LearnerProfileORM,
    LearnerTierProgressORM,
    LearningAttemptORM,
)
from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
    GenerateRequest,
    LearnerProfile,
    SkillNode,
)
from app.services.generation.continuation_uow import (
    ContinuationAtomicityError,
    ContinuationUnitOfWork,
)
from app.services.generation.generation import GenerationService
from app.services.generation.jobs import GenerationJobService
from app.services.learners.mastery import MasteryService
from app.services.learning_documents.resources import ResourceService
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker


def _memory_fixture(*, feedback_ids=True, lower_tier=False):
    learner_repository = MemoryLearnerRepository()
    learner = LearnerProfile(
        learner_id="continuation-learner",
        user_id="owner",
        learner_type="test",
        education="本科",
        major="软件",
        learning_goal="continuation-atomicity",
        knowledge_base_id="continuation-kb",
        skill_level="中级" if lower_tier else "初级",
    )
    learner_repository.save(learner)
    nodes = [
        SkillNode(
            node_id="selected",
            knowledge_base_id=learner.knowledge_base_id,
            name="Selected",
            tier=1,
        ),
        SkillNode(
            node_id="waiter",
            knowledge_base_id=learner.knowledge_base_id,
            name="Waiter",
            tier=2 if lower_tier else 1,
        ),
    ]
    mastery_repository = MemoryMasteryRepository(learner_repository)
    curriculum_repository = MemoryCurriculumRepository()
    tier_repository = MemoryTierProgressRepository()
    resource_repository = MemoryResourceRepository()
    mastery = MasteryService(
        mastery_repository,
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        resource_repo=resource_repository,
        curriculum_repo=curriculum_repository,
        tier_progress_repo=tier_repository,
    )
    job_repository = MemoryGenerationJobRepository()
    generation_service = GenerationService(
        resource_repo=resource_repository, workflow=None
    )
    jobs = GenerationJobService(
        job_repository, generation_service, mastery_service=mastery
    )

    constraints = (
        {"feedback_attempt_id": "attempt", "feedback_decision_id": "decision"}
        if feedback_ids
        else {}
    )
    if lower_tier:
        constraints["selection_type"] = "lower_tier_selection"
    original_request = GenerateRequest(
        learner_id=learner.learner_id,
        topic="transaction fixture",
        knowledge_base_id=learner.knowledge_base_id,
        target_skill_nodes=["selected"],
        resource_types=["讲义"],
        constraints=constraints,
    )
    job_repository.create(
        run_id="source-run",
        batch_id="batch",
        learner_id=learner.learner_id,
        topic=original_request.topic,
        knowledge_base_id=learner.knowledge_base_id,
        request_payload=original_request.model_dump(mode="json"),
    )
    feedback_repository = MemoryFeedbackLoopRepository(
        learner_repository, mastery_repository
    )

    def create(payload=None):
        return jobs.create_continuation(
            learner,
            "batch",
            payload
            or ContinueResourceBatchRequest(
                learner_id=learner.learner_id,
                resource_types=["讲义"],
                source_run_id="source-run",
                replace_source_run=True,
            ),
            resource_service_factory=lambda: ResourceService(resource_repository),
            feedback_repo_factory=lambda: feedback_repository,
        )

    return SimpleNamespace(
        learner=learner,
        learner_repository=learner_repository,
        mastery=mastery,
        mastery_repository=mastery_repository,
        curriculum_repository=curriculum_repository,
        tier_repository=tier_repository,
        resource_repository=resource_repository,
        job_repository=job_repository,
        feedback_repository=feedback_repository,
        jobs=jobs,
        create=create,
    )


def test_memory_learner_repository_keeps_live_profile_identity():
    graph = _memory_fixture(feedback_ids=False)

    assert graph.learner_repository.get(graph.learner.learner_id) is graph.learner
    assert (
        graph.learner_repository.list_all()[graph.learner.learner_id] is graph.learner
    )

    graph.learner.learning_goal = "mutated through existing live reference"
    assert graph.learner_repository.get(graph.learner.learner_id).learning_goal == (
        "mutated through existing live reference"
    )


def _sql_fixture(*, feedback_ids=True, mastery_enabled=False):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    now = datetime.now(UTC)
    with session_factory() as db:
        db.add(
            LearnerProfileORM(
                learner_id="continuation-learner",
                learner_type="test",
                education="本科",
                major="软件",
                learning_goal="continuation-atomicity",
                skill_level="中级" if mastery_enabled else "初级",
                knowledge_base_id="continuation-kb" if mastery_enabled else None,
                theory_scores={},
                knowledge_states={},
                weak_points=[],
                strong_points=[],
                learning_preferences={},
                last_feedback_summary={},
                profile_version=1,
            )
        )
        db.add(
            AgentRunORM(
                run_id="source-run",
                learner_id="continuation-learner",
                status="completed",
            )
        )
        if feedback_ids:
            db.add(
                GeneratedResourceORM(
                    resource_id="feedback-resource",
                    learner_id="continuation-learner",
                    topic="transaction fixture",
                    resource_type="讲义",
                    difficulty="初级",
                )
            )
        db.commit()
        if feedback_ids:
            db.add(
                LearningAttemptORM(
                    attempt_id="attempt",
                    learner_id="continuation-learner",
                    source_resource_id="feedback-resource",
                    source_resource_version=1,
                    idempotency_key="fixture",
                    request_hash="a" * 64,
                    expected_profile_version=1,
                    overall_score=0.8,
                    submitted_at=now,
                )
            )
            db.add(
                FeedbackDecisionORM(
                    decision_id="decision",
                    learner_id="continuation-learner",
                    attempt_id="attempt",
                    action="advance",
                    decision_reason="fixture",
                    decision_hash="b" * 64,
                    created_at=now,
                )
            )
            db.commit()

    job_repository = SQLGenerationJobRepository(session_factory)
    feedback_repository = SQLFeedbackLoopRepository(session_factory)
    if feedback_ids:
        # Keep this test focused on transactional attachment, not feedback result projection.
        feedback_repository._load_result = lambda _db, _attempt_id, replay: (
            SimpleNamespace(
                idempotent_replay=replay,
            )
        )
    resource_repository = SQLResourceRepository(session_factory)
    request_constraints = (
        {"feedback_attempt_id": "attempt", "feedback_decision_id": "decision"}
        if feedback_ids
        else {}
    )
    if mastery_enabled:
        request_constraints["selection_type"] = "lower_tier_selection"
    original_request = GenerateRequest(
        learner_id="continuation-learner",
        topic="transaction fixture",
        knowledge_base_id="continuation-kb" if mastery_enabled else None,
        target_skill_nodes=["selected"] if mastery_enabled else [],
        resource_types=["讲义"],
        constraints=request_constraints,
    )
    job_repository.create(
        run_id="source-run",
        batch_id="batch",
        learner_id="continuation-learner",
        topic=original_request.topic,
        knowledge_base_id=original_request.knowledge_base_id,
        request_payload=original_request.model_dump(mode="json"),
    )
    learner = LearnerProfile(
        learner_id="continuation-learner",
        user_id="owner",
        learner_type="test",
        education="本科",
        major="软件",
        learning_goal="continuation-atomicity",
        knowledge_base_id="continuation-kb" if mastery_enabled else None,
        skill_level="中级" if mastery_enabled else "初级",
    )
    mastery = None
    if mastery_enabled:
        nodes = [
            SkillNode(
                node_id="selected",
                knowledge_base_id="continuation-kb",
                name="Selected",
                tier=1,
            ),
            SkillNode(
                node_id="waiter",
                knowledge_base_id="continuation-kb",
                name="Waiter",
                tier=2,
            ),
        ]
        mastery = MasteryService(
            SQLMasteryRepository(session_factory),
            SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
            resource_repo=resource_repository,
            curriculum_repo=SQLCurriculumRepository(session_factory),
            tier_progress_repo=SQLTierProgressRepository(session_factory),
        )
    jobs = GenerationJobService(
        job_repository,
        GenerationService(resource_repo=resource_repository, workflow=None),
        mastery_service=mastery,
    )
    feedback_calls = []

    def create(payload=None):
        return jobs.create_continuation(
            learner,
            "batch",
            payload
            or ContinueResourceBatchRequest(
                learner_id=learner.learner_id,
                resource_types=["讲义"],
                source_run_id="source-run",
                replace_source_run=True,
            ),
            resource_service_factory=lambda: ResourceService(resource_repository),
            feedback_repo_factory=lambda: (
                feedback_calls.append(True) or feedback_repository
            ),
        )

    return SimpleNamespace(
        engine=engine,
        session_factory=session_factory,
        learner=learner,
        jobs=jobs,
        job_repository=job_repository,
        feedback_repository=feedback_repository,
        resource_repository=resource_repository,
        mastery=mastery,
        feedback_calls=feedback_calls,
        create=create,
    )


def _continuation_payload(learner_id="continuation-learner"):
    return ContinueResourceBatchRequest(
        learner_id=learner_id,
        resource_types=["讲义"],
        source_run_id="source-run",
        replace_source_run=True,
    )


def _memory_state(graph):
    return {
        "jobs": deepcopy(graph.job_repository._store),
        "followups": deepcopy(graph.feedback_repository._followups),
        "mastery_states": deepcopy(graph.mastery_repository._states),
        "mastery_events": deepcopy(graph.mastery_repository._events),
        "node_names": deepcopy(graph.mastery_repository._node_names),
        "curriculum": deepcopy(graph.curriculum_repository._rows),
        "tier": deepcopy(graph.tier_repository._states),
        "profile": graph.learner_repository.get(graph.learner.learner_id),
    }


def test_memory_followup_failure_rolls_back_job_focus_curriculum_and_profile(
    monkeypatch,
):
    graph = _memory_fixture()
    before = _memory_state(graph)

    def attach_then_fail(**payload):
        graph.feedback_repository._followups.setdefault(
            payload["attempt_id"], []
        ).append(dict(payload))
        raise RuntimeError("injected follow-up failure")

    monkeypatch.setattr(graph.feedback_repository, "attach_followup", attach_then_fail)
    with pytest.raises(RuntimeError, match="injected follow-up failure"):
        graph.create(_continuation_payload())

    after = _memory_state(graph)
    assert after["jobs"] == before["jobs"]
    assert after["followups"] == before["followups"]
    assert after["mastery_states"] == before["mastery_states"]
    assert after["mastery_events"] == before["mastery_events"]
    assert after["node_names"] == before["node_names"]
    assert after["curriculum"] == before["curriculum"]
    assert after["tier"] == before["tier"]
    assert after["profile"] == before["profile"]
    assert graph.learner_repository.get(graph.learner.learner_id) is graph.learner
    assert graph.job_repository.get("source-run").superseded_by_run_id is None


def test_memory_supersede_failure_rolls_back_prior_followup_write(monkeypatch):
    graph = _memory_fixture()
    before = _memory_state(graph)
    original_supersede = graph.job_repository.mark_superseded

    def attach_followup(**payload):
        graph.feedback_repository._followups.setdefault(
            payload["attempt_id"], []
        ).append(dict(payload))
        return SimpleNamespace()

    def supersede_then_fail(run_id, replacement_run_id):
        original_supersede(run_id, replacement_run_id)
        raise RuntimeError("injected supersede failure")

    monkeypatch.setattr(graph.feedback_repository, "attach_followup", attach_followup)
    monkeypatch.setattr(graph.job_repository, "mark_superseded", supersede_then_fail)
    with pytest.raises(RuntimeError, match="injected supersede failure"):
        graph.create(_continuation_payload())

    assert graph.job_repository._store == before["jobs"]
    assert graph.feedback_repository._followups == before["followups"]
    assert graph.mastery_repository._states == before["mastery_states"]
    assert graph.curriculum_repository._rows == before["curriculum"]
    assert graph.tier_repository._states == before["tier"]
    assert graph.learner_repository.get(graph.learner.learner_id) == before["profile"]


def test_memory_rollback_waits_for_and_preserves_concurrent_job_write(monkeypatch):
    graph = _memory_fixture()
    attach_started = Event()
    continue_rollback = Event()
    writer_started = Event()
    writer_finished = Event()
    errors = []

    def attach_then_pause(**_payload):
        attach_started.set()
        assert continue_rollback.wait(timeout=5)
        raise RuntimeError("injected follow-up failure")

    monkeypatch.setattr(graph.feedback_repository, "attach_followup", attach_then_pause)

    def run_continuation():
        try:
            graph.create(_continuation_payload())
        except RuntimeError as exc:
            errors.append(exc)

    continuation_thread = Thread(target=run_continuation)
    continuation_thread.start()
    assert attach_started.wait(timeout=5)

    original_create = graph.job_repository.create

    def concurrent_create(**kwargs):
        writer_started.set()
        try:
            return original_create(**kwargs)
        finally:
            writer_finished.set()

    monkeypatch.setattr(graph.job_repository, "create", concurrent_create)
    writer_thread = Thread(
        target=lambda: graph.job_repository.create(
            run_id="concurrent-run",
            batch_id="other-batch",
            learner_id=graph.learner.learner_id,
            topic="concurrent write",
            knowledge_base_id=graph.learner.knowledge_base_id,
            request_payload={},
        )
    )
    writer_thread.start()
    assert writer_started.wait(timeout=5)
    try:
        assert not writer_finished.wait(timeout=0.05)
    finally:
        continue_rollback.set()
    continuation_thread.join(timeout=5)
    writer_thread.join(timeout=5)

    assert not continuation_thread.is_alive()
    assert not writer_thread.is_alive()
    assert errors and str(errors[0]) == "injected follow-up failure"
    assert graph.job_repository.get("concurrent-run") is not None
    assert graph.job_repository.get("source-run") is not None
    assert len(graph.job_repository.list_by_learner(graph.learner.learner_id)) == 2


def test_memory_schedule_failure_restores_wait_debt_then_keeps_failed_job(monkeypatch):
    graph = _memory_fixture(feedback_ids=True, lower_tier=True)
    before_curriculum = deepcopy(graph.curriculum_repository._rows)
    before_tier = deepcopy(graph.tier_repository._states)
    before_mastery = deepcopy(graph.mastery_repository._states)
    before_events = deepcopy(graph.mastery_repository._events)
    before_profile = graph.learner_repository.get(graph.learner.learner_id)
    schedule = graph.mastery.schedule_generation

    def schedule_then_fail(learner, **kwargs):
        schedule(learner, **kwargs)
        raise RuntimeError("injected schedule failure")

    monkeypatch.setattr(graph.mastery, "schedule_generation", schedule_then_fail)
    with pytest.raises(RuntimeError, match="injected schedule failure"):
        graph.create(_continuation_payload())

    jobs = graph.job_repository.list_by_learner(graph.learner.learner_id)
    failed = [item for item in jobs if item.run_id != "source-run"]
    assert len(failed) == 1
    assert failed[0].job_status == "failed"
    assert failed[0].error_message == "CURRICULUM_SCHEDULE_FAILED"
    assert graph.job_repository.get("source-run").superseded_by_run_id is None
    assert graph.feedback_repository._followups == {}
    assert graph.curriculum_repository._rows == before_curriculum
    assert graph.tier_repository._states == before_tier
    assert graph.mastery_repository._states == before_mastery
    assert graph.mastery_repository._events == before_events
    assert graph.learner_repository.get(graph.learner.learner_id) == before_profile
    assert graph.learner_repository.get(graph.learner.learner_id) is graph.learner


def test_memory_successful_repeated_continuation_still_creates_new_runs():
    graph = _memory_fixture(feedback_ids=False)
    first, _ = graph.create(_continuation_payload())
    second, _ = graph.create(_continuation_payload())

    assert first.run_id != second.run_id
    assert graph.job_repository.get(first.run_id).job_status == "queued"
    assert graph.job_repository.get(second.run_id).job_status == "queued"
    assert graph.job_repository.get("source-run").superseded_by_run_id == second.run_id


def test_custom_mutator_cannot_claim_atomicity_with_standard_repositories():
    graph = _memory_fixture(feedback_ids=False)
    before = deepcopy(graph.job_repository._store)
    graph.jobs.create_job = lambda *_args, **_kwargs: pytest.fail(
        "custom mutation must be rejected before job creation"
    )

    with pytest.raises(
        ContinuationAtomicityError, match="custom continuation mutators"
    ):
        graph.create(_continuation_payload())

    assert graph.job_repository._store == before


def test_mixed_sql_and_memory_writers_reject_before_any_job_write():
    graph = _sql_fixture()
    memory_feedback_repository = MemoryFeedbackLoopRepository(MemoryLearnerRepository())

    with pytest.raises(ContinuationAtomicityError, match="mix SQL and Memory"):
        graph.jobs.create_continuation(
            graph.learner,
            "batch",
            _continuation_payload(),
            resource_service_factory=lambda: ResourceService(graph.resource_repository),
            feedback_repo_factory=lambda: memory_feedback_repository,
        )

    with graph.session_factory() as db:
        child_rows = (
            db.query(GenerationJobORM)
            .filter(GenerationJobORM.run_id != "source-run")
            .all()
        )
        source = db.get(GenerationJobORM, "source-run")
    assert child_rows == []
    assert source.superseded_by_run_id is None


def test_sql_feedback_inner_commit_is_rolled_back_with_continuation(monkeypatch):
    graph = _sql_fixture()
    checked_out = set()
    maximum_checked_out = 0

    def on_checkout(connection, _record, _proxy):
        nonlocal maximum_checked_out
        checked_out.add(id(connection))
        maximum_checked_out = max(maximum_checked_out, len(checked_out))

    def on_checkin(connection, _record):
        checked_out.discard(id(connection))

    event.listen(graph.engine, "checkout", on_checkout)
    event.listen(graph.engine, "checkin", on_checkin)
    original_attach = SQLFeedbackLoopRepository.attach_followup

    def attach_then_fail(repository, **payload):
        original_attach(repository, **payload)
        raise RuntimeError("injected after repository commit")

    monkeypatch.setattr(SQLFeedbackLoopRepository, "attach_followup", attach_then_fail)
    try:
        with pytest.raises(RuntimeError, match="after repository commit"):
            graph.create(_continuation_payload())
        with graph.session_factory() as db:
            relation_count = db.query(FeedbackFollowUpRunORM).count()
            child_rows = (
                db.query(GenerationJobORM)
                .filter(GenerationJobORM.run_id != "source-run")
                .all()
            )
            source = db.get(GenerationJobORM, "source-run")
        assert relation_count == 0
        assert child_rows == []
        assert source.superseded_by_run_id is None
        assert maximum_checked_out == 1
        assert graph.feedback_calls
    finally:
        event.remove(graph.engine, "checkout", on_checkout)
        event.remove(graph.engine, "checkin", on_checkin)
        graph.engine.dispose()


def test_sql_outer_commit_failure_rolls_back_job_and_supersede(monkeypatch):
    graph = _sql_fixture(feedback_ids=False)

    def fail_commit(_unit_of_work):
        raise RuntimeError("injected outer commit failure")

    monkeypatch.setattr(
        ContinuationUnitOfWork, "_commit_outer_transaction", fail_commit
    )
    try:
        with pytest.raises(RuntimeError, match="outer commit failure"):
            graph.create(_continuation_payload())
        with graph.session_factory() as db:
            child_rows = (
                db.query(GenerationJobORM)
                .filter(GenerationJobORM.run_id != "source-run")
                .all()
            )
            source = db.get(GenerationJobORM, "source-run")
        assert child_rows == []
        assert source.superseded_by_run_id is None
    finally:
        graph.engine.dispose()


def test_sql_mastery_schedule_failure_rolls_back_progress_but_keeps_failed_job(
    monkeypatch,
):
    graph = _sql_fixture(feedback_ids=False, mastery_enabled=True)
    schedule = MasteryService.schedule_generation

    def schedule_then_fail(service, learner, **kwargs):
        schedule(service, learner, **kwargs)
        raise RuntimeError("injected SQL schedule failure")

    monkeypatch.setattr(MasteryService, "schedule_generation", schedule_then_fail)
    try:
        with pytest.raises(RuntimeError, match="SQL schedule failure"):
            graph.create(_continuation_payload())
        with graph.session_factory() as db:
            failed = (
                db.query(GenerationJobORM)
                .filter(GenerationJobORM.run_id != "source-run")
                .all()
            )
            curriculum_count = db.query(LearnerCurriculumNodeORM).count()
            tier_count = db.query(LearnerTierProgressORM).count()
            mastery_count = db.query(KnowledgeStateORM).count()
            event_count = db.query(AbilityStateEventORM).count()
            profile = db.get(LearnerProfileORM, "continuation-learner")
            source = db.get(GenerationJobORM, "source-run")
        assert len(failed) == 1
        assert failed[0].status == "failed"
        assert failed[0].error_message == "CURRICULUM_SCHEDULE_FAILED"
        assert curriculum_count == 0
        assert tier_count == 0
        assert mastery_count == 0
        assert event_count == 0
        assert profile.knowledge_states == {}
        assert source.superseded_by_run_id is None
    finally:
        graph.engine.dispose()


def test_memory_continuation_failure_does_not_register_background_job(monkeypatch):
    graph = _memory_fixture()
    called = []

    def attach_then_fail(**payload):
        graph.feedback_repository._followups.setdefault(
            payload["attempt_id"], []
        ).append(dict(payload))
        raise RuntimeError("injected follow-up failure")

    monkeypatch.setattr(graph.feedback_repository, "attach_followup", attach_then_fail)
    monkeypatch.setattr(documents, "get_settings", lambda: object())
    monkeypatch.setattr(
        documents,
        "build_health_report",
        lambda _settings: SimpleNamespace(status="ready", error_codes=[]),
    )
    graph.jobs.run_job = lambda *args: called.append(args)
    app = FastAPI()

    @app.middleware("http")
    async def current_user(request, call_next):
        request.state.current_user = SimpleNamespace(user_id="owner")
        return await call_next(request)

    app.container = SimpleNamespace(
        profile_service=lambda: SimpleNamespace(get=lambda _learner_id: graph.learner),
        generation_job_service=lambda: graph.jobs,
        resource_service=lambda: ResourceService(graph.resource_repository),
        feedback_service=lambda: SimpleNamespace(
            feedback_loop_repo=graph.feedback_repository
        ),
    )
    app.include_router(documents.router, prefix="/api/resources")
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/resources/batches/batch/continuations",
        json={
            "learner_id": graph.learner.learner_id,
            "resource_types": ["讲义"],
            "source_run_id": "source-run",
            "replace_source_run": True,
        },
    )
    assert response.status_code == 500
    assert called == []
    assert graph.job_repository.list_by_learner(graph.learner.learner_id) == [
        graph.job_repository.get("source-run")
    ]
    assert graph.job_repository.get("source-run").superseded_by_run_id is None
