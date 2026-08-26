from datetime import datetime, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_sql_repository import SQLFeedbackLoopRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.shared.models import Base
from app.db.learning_documents.sql_repository import SQLResourceRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult, LearningAttemptSubmit
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.generation.jobs import GenerationJobService


class _NoopGenerationService:
    pass


def test_sqlite_feedback_state_survives_repository_reconstruction(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'restart.db'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
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
    )
    resources.save(resource, "learner", "检索")
    loop = SQLFeedbackLoopRepository(factory)
    service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=loop,
        generation_job_service=GenerationJobService(SQLGenerationJobRepository(factory), _NoopGenerationService()),
    )
    result = service.process_learning_attempt(
        learners.get("learner"),
        resources.get("resource"),
        LearningAttemptSubmit(
            learner_id="learner",
            source_resource_id="resource",
            source_resource_version=1,
            idempotency_key="restart-idempotency",
            expected_profile_version=1,
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a",
                question_ids=["q1"],
                correct_count=4,
                total_count=10,
            )],
        ),
    )
    assert result.followup_generation_status == "not_requested"

    restarted_loop = SQLFeedbackLoopRepository(sessionmaker(bind=create_engine(f"sqlite:///{tmp_path / 'restart.db'}")))
    restarted_learners = SQLLearnerRepository(restarted_loop.session_factory)
    profile = restarted_learners.get("learner")
    replay = restarted_loop.get_by_idempotency_key("learner", "restart-idempotency")
    assert profile.profile_version == 2
    assert profile.knowledge_states["skill-a"].score == 0.4
    assert replay.attempt.attempt_id == result.attempt.attempt_id
    assert replay.followup_run_id is None
    assert restarted_loop.get_current_path("learner").path_id == result.learning_path.path_id
    assert restarted_loop.list_profile_versions("learner")[0].source_attempt_id == result.attempt.attempt_id
