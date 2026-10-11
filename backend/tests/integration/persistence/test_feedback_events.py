from datetime import datetime, timezone

import pytest

from app.db.audit.memory import MemoryAuditRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult, LearningAttemptSubmit
from app.models.shared.persistence import CreateRunCommand, WorkflowEventType, canonical_hash
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService


class _NoopGenerationService:
    pass


def _feedback_case():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="kb",
        learning_goal="闭环",
    )
    learners.save(profile)
    audit = MemoryAuditRepository()
    now = datetime.now(timezone.utc)
    snapshot = {"learner_id": "learner", "topic": "检索"}
    audit.create_run(CreateRunCommand(
        run_id="source-run",
        learner_id="learner",
        knowledge_base_id="kb",
        topic="检索",
        request_snapshot=snapshot,
        request_hash=canonical_hash(snapshot),
        occurred_at=now,
    ))
    audit.start_run("source-run", occurred_at=now)
    service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=MemoryFeedbackLoopRepository(learners),
        generation_job_service=GenerationJobService(MemoryGenerationJobRepository(), _NoopGenerationService()),
        audit_repo=audit,
    )
    resource = LearningResource(
        resource_id="resource",
        learner_id="learner",
        topic="检索",
        resource_type="测试题",
        difficulty="初级",
        content_text="测试",
        knowledge_points=["skill-a"],
        source_refs=[],
        publication_status="published",
        run_id="source-run",
    )
    request = LearningAttemptSubmit(
            learner_id="learner",
            source_resource_id="resource",
            source_run_id="source-run",
            idempotency_key="event-idempotency",
            expected_profile_version=1,
            submitted_at=now,
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a",
                question_ids=["q1"],
                correct_count=4,
                total_count=10,
            )],
        )
    return service, learners, profile, resource, request, audit


def test_feedback_facts_append_sanitized_events_to_source_run():
    service, _, profile, resource, request, audit = _feedback_case()
    service.process_learning_attempt(profile, resource, request)
    events = audit.list_events("source-run", limit=100)
    event_types = [item.event_type for item in events]
    for expected in (
        WorkflowEventType.ATTEMPT_SUBMITTED,
        WorkflowEventType.FEEDBACK_DECISION_STARTED,
        WorkflowEventType.FEEDBACK_DECISION_COMPLETED,
        WorkflowEventType.KNOWLEDGE_STATE_UPDATED,
        WorkflowEventType.PROFILE_UPDATED,
        WorkflowEventType.PATH_MUTATED,
    ):
        assert expected in event_types
    assert WorkflowEventType.FOLLOWUP_GENERATION_CREATED not in event_types
    payload_text = str([item.payload for item in events])
    assert "question_ids" not in payload_text
    assert "answer" not in payload_text.lower()


FEEDBACK_TYPES = (
    WorkflowEventType.ATTEMPT_SUBMITTED,
    WorkflowEventType.FEEDBACK_DECISION_STARTED,
    WorkflowEventType.FEEDBACK_DECISION_COMPLETED,
    WorkflowEventType.KNOWLEDGE_STATE_UPDATED,
    WorkflowEventType.PROFILE_UPDATED,
    WorkflowEventType.PATH_MUTATED,
)


@pytest.mark.parametrize("failure_at", [0, 2, 5])
@pytest.mark.parametrize("commit_before_error", [False, True])
def test_feedback_retry_repairs_event_suffix_in_order(monkeypatch, failure_at, commit_before_error):
    service, learners, profile, resource, request, audit = _feedback_case()
    original = audit.append_event
    failed = False

    def intermittent(run_id, event_type, **kwargs):
        nonlocal failed
        if event_type == FEEDBACK_TYPES[failure_at] and not failed:
            failed = True
            if commit_before_error:
                original(run_id, event_type, **kwargs)
            raise RuntimeError("synthetic audit outage")
        return original(run_id, event_type, **kwargs)

    monkeypatch.setattr(audit, "append_event", intermittent)
    first = service.process_learning_attempt(profile, resource, request)
    prefix = [item.event_type for item in audit.list_events("source-run") if item.event_type in FEEDBACK_TYPES]
    assert prefix == list(FEEDBACK_TYPES[:failure_at + int(commit_before_error)])
    version = learners.get("learner").profile_version
    retried = service.process_learning_attempt(profile, resource, request)
    service.process_learning_attempt(profile, resource, request)
    events = [item for item in audit.list_events("source-run") if item.event_type in FEEDBACK_TYPES]
    assert [item.event_type for item in events] == list(FEEDBACK_TYPES)
    assert len({item.event_id for item in events}) == 6
    assert retried.attempt.attempt_id == first.attempt.attempt_id
    assert learners.get("learner").profile_version == version
    assert len(service.feedback_loop_repo.list_attempts("learner", 100)) == 1


def test_audit_lookup_failure_does_not_undo_committed_feedback(monkeypatch):
    service, _, profile, resource, request, audit = _feedback_case()
    original = audit.get_run
    monkeypatch.setattr(audit, "get_run", lambda _: (_ for _ in ()).throw(RuntimeError("synthetic lookup outage")))
    result = service.process_learning_attempt(profile, resource, request)
    monkeypatch.setattr(audit, "get_run", original)
    retried = service.process_learning_attempt(profile, resource, request)
    assert retried.attempt.attempt_id == result.attempt.attempt_id
    assert [item.event_type for item in audit.list_events("source-run") if item.event_type in FEEDBACK_TYPES] == list(FEEDBACK_TYPES)
