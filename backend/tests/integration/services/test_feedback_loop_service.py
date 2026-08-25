from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.core.security.errors import ApplicationError, ErrorCode
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.models.feedback.feedback_loop import (
    FeedbackFollowupSelection,
    KnowledgePointAttemptResult,
    LearningAttemptSubmit,
)
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService
from app.services.learners.mastery import MasteryService


class _NoopGenerationService:
    pass


def _setup():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="kb",
        learning_goal="完成闭环",
    )
    learners.save(profile)
    resource = LearningResource(
        resource_id="resource",
        learner_id="learner",
        topic="检索",
        resource_type="分阶测试题",
        difficulty="初级",
        content_text="测试",
        knowledge_points=["skill-a"],
        source_refs=[],
        publication_status="published",
        run_id="source-run",
        batch_id="source-batch",
    )
    loop = MemoryFeedbackLoopRepository(learners)
    jobs = MemoryGenerationJobRepository()
    service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=loop,
        generation_job_service=GenerationJobService(jobs, _NoopGenerationService()),
    )
    return service, learners, jobs, profile, resource


def _request(score: float, *, key="idempotency-key", version=1):
    return LearningAttemptSubmit(
        learner_id="learner",
        source_resource_id="resource",
        source_resource_version=1,
        source_run_id="source-run",
        idempotency_key=key,
        expected_profile_version=version,
        submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q1"],
            correct_count=round(score * 100),
            total_count=100,
        )],
    )


def test_low_attempt_updates_profile_path_and_returns_manual_resource_options():
    service, learners, jobs, profile, resource = _setup()
    scheduled = []
    result = service.process_learning_attempt(
        profile,
        resource,
        _request(0.4),
        schedule_followup=lambda learner, req, run_id: scheduled.append((learner, req, run_id)),
    )
    persisted = learners.get("learner")
    assert result.decision.action == "remediate"
    assert result.profile_version == 2
    assert persisted.profile_version == 2
    assert persisted.knowledge_states["skill-a"].score == 0.4
    assert result.path_mutation.inserted_node_ids
    assert result.followup_generation_status == "not_requested"
    assert result.followup_run_id is None
    assert result.resource_options
    assert jobs.list_by_learner("learner") == []
    assert scheduled == []

    selected = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner",
            attempt_id=result.attempt.attempt_id,
            option_id=result.resource_options[0].option_id,
            resource_types=["讲义", "分阶测试题"],
            difficulty="高级",
        ),
        schedule_followup=lambda learner, req, run_id: scheduled.append((learner, req, run_id)),
    )
    assert selected.followup_generation_status == "queued"
    assert jobs.get(selected.followup_run_id).job_status == "queued"
    assert jobs.get(selected.followup_run_id).request_payload["resource_types"] == ["讲义", "分阶测试题"]
    assert jobs.get(selected.followup_run_id).request_payload["difficulty_preference"] == "高级"
    assert "must_include_citations" not in jobs.get(selected.followup_run_id).request_payload["constraints"]
    relation = service.feedback_loop_repo.get_followup_relation(selected.followup_run_id)
    assert relation["attempt_id"] == result.attempt.attempt_id
    assert len(scheduled) == 1


def test_practice_updates_state_without_unnecessary_generation():
    service, _, jobs, profile, resource = _setup()
    result = service.process_learning_attempt(profile, resource, _request(0.7))
    assert result.decision.action == "practice"
    assert result.followup_generation_status == "not_requested"
    assert jobs.list_by_learner("learner") == []


def test_custom_followup_selection_generates_the_checked_resource_types():
    service, learners, jobs, profile, resource = _setup()
    result = service.process_learning_attempt(profile, resource, _request(0.4))

    selected_types = ["讲义", "实操指南", "分阶测试题"]
    selected = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner",
            attempt_id=result.attempt.attempt_id,
            option_id="custom-selection",
            resource_types=selected_types,
            difficulty="初级",
        ),
    )

    assert selected.followup_generation_status == "queued"
    followup_job = jobs.get(selected.followup_run_id)
    assert followup_job.request_payload["resource_types"] == selected_types
    assert followup_job.request_payload["difficulty_preference"] == "初级"
    assert "must_include_citations" not in followup_job.request_payload["constraints"]
    relation = service.feedback_loop_repo.get_followup_relation(selected.followup_run_id)
    assert relation["parent_run_id"] == "source-run"


def test_same_idempotency_key_replays_without_second_profile_update_or_job():
    service, learners, jobs, profile, resource = _setup()
    request = _request(0.4)
    first = service.process_learning_attempt(profile, resource, request)
    second = service.process_learning_attempt(learners.get("learner"), resource, request)
    assert second.idempotent_replay is True
    assert second.attempt.attempt_id == first.attempt.attempt_id
    assert learners.get("learner").profile_version == 2
    assert second.followup_generation_status == "not_requested"
    assert len(jobs.list_by_learner("learner")) == 0


def test_same_key_with_different_payload_is_409_conflict():
    service, learners, _, profile, resource = _setup()
    service.process_learning_attempt(profile, resource, _request(0.4))
    with pytest.raises(ApplicationError) as exc:
        service.process_learning_attempt(
            learners.get("learner"),
            resource,
            _request(0.7),
        )
    assert exc.value.code == ErrorCode.FEEDBACK_IDEMPOTENCY_CONFLICT
    assert exc.value.status_code == 409


def test_stale_profile_version_is_rejected_without_mutation():
    service, learners, _, profile, resource = _setup()
    service.process_learning_attempt(profile, resource, _request(0.7, key="first-key"))
    with pytest.raises(ApplicationError) as exc:
        service.process_learning_attempt(
            learners.get("learner"),
            resource,
            _request(0.7, key="second-key", version=1),
        )
    assert exc.value.code == ErrorCode.LEARNER_PROFILE_VERSION_CONFLICT
    assert learners.get("learner").profile_version == 2


def test_followup_is_only_created_after_user_selection():
    service, learners, jobs, profile, resource = _setup()
    service.generation_job_service = None
    request = _request(0.4)
    result = service.process_learning_attempt(profile, resource, request)
    assert result.followup_generation_status == "not_requested"

    service.generation_job_service = GenerationJobService(jobs, _NoopGenerationService())
    selected = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner",
            attempt_id=result.attempt.attempt_id,
            option_id=result.resource_options[0].option_id,
        ),
    )
    repeated = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner",
            attempt_id=result.attempt.attempt_id,
            option_id=result.resource_options[0].option_id,
        ),
    )

    assert selected.followup_generation_status == "queued"
    assert selected.followup_run_id == repeated.followup_run_id
    assert len(jobs.list_by_learner("learner")) == 1


def test_feedback_intent_only_accepts_server_returned_reinforcement_nodes():
    service, learners, jobs, profile, resource = _setup()
    nodes = [SimpleNamespace(
        node_id="skill-a", name="A", description=None, level="L1",
        prerequisites=[], children=["skill-b"],
    ), SimpleNamespace(
        node_id="skill-b", name="B", description=None, level="L2",
        prerequisites=["skill-a"], children=[],
    )]
    service.mastery_service = MasteryService(
        MemoryMasteryRepository(learners),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        resource_repo=SimpleNamespace(list_by_learner=lambda _learner_id: [resource]),
    )
    result = service.process_learning_attempt(profile, resource, _request(0.4))
    options = result.generation_options
    assert [item.skill_node_id for item in options.reinforce_weakness] == ["skill-a"]
    assert options.learn_new_knowledge == []

    selected = service.choose_followup(
        learners.get("learner"),
        FeedbackFollowupSelection(
            learner_id="learner", attempt_id=result.attempt.attempt_id,
            option_id="personalized-correction-package-v1",
            learning_intent="reinforce_weakness", selected_skill_node_ids=["skill-a"],
            next_generation_snapshot_hash=options.snapshot_hash,
        ),
    )
    assert jobs.get(selected.followup_run_id).request_payload["target_skill_nodes"] == ["skill-a"]
    payload = jobs.get(selected.followup_run_id).request_payload
    assert payload["resource_types"] == ["个性化纠错训练包"]
    assert payload["constraints"]["correction_focus_snapshot"]["ordered_target_nodes"][0]["skill_node_id"] == "skill-a"
    assert "must_include_citations" not in payload["constraints"]
    assert jobs.get(selected.followup_run_id).batch_id == "source-batch"

    with pytest.raises(ApplicationError):
        service.choose_followup(
            learners.get("learner"),
            FeedbackFollowupSelection(
                learner_id="learner", attempt_id=result.attempt.attempt_id,
                option_id="personalized-correction-package-v1",
                learning_intent="reinforce_weakness", selected_skill_node_ids=["skill-b"],
                next_generation_snapshot_hash=options.snapshot_hash,
            ),
        )
