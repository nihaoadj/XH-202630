from datetime import datetime, timezone

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


def test_feedback_facts_append_sanitized_events_to_source_run():
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
    service.process_learning_attempt(
        profile,
        resource,
        LearningAttemptSubmit(
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
        ),
    )
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
