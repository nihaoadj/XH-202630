from datetime import datetime, timezone

from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback_loop.memory import MemoryFeedbackLoopRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.feedback_loop import KnowledgePointAttemptResult, LearningAttemptSubmit
from app.models.schemas import LearnerProfile, LearningResource
from app.services.feedback_service import FeedbackService
from app.services.report_service import ReportService


def test_report_reads_persisted_profile_path_attempt_and_version_history():
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
    resources = MemoryResourceRepository()
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
    loop = MemoryFeedbackLoopRepository(learners)
    feedback = MemoryFeedbackRepository()
    FeedbackService(feedback, feedback_loop_repo=loop).process_learning_attempt(
        profile,
        resource,
        LearningAttemptSubmit(
            learner_id="learner",
            source_resource_id="resource",
            idempotency_key="report-idempotency",
            expected_profile_version=1,
            submitted_at=datetime(2026, 8, 11, tzinfo=timezone.utc),
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a",
                question_ids=["q1"],
                correct_count=7,
                total_count=10,
            )],
        ),
    )
    report = ReportService(resources, feedback, loop).build_report(learners.get("learner"))
    assert report["profile_version"] == 2
    assert report["knowledge_mastery"]["skill-a"]["score"] == 0.7
    assert report["current_learning_path"]["path_id"]
    assert len(report["recent_attempts"]) == 1
    assert report["recent_feedback_decisions"][0]["action"] == "practice"
    assert report["recent_knowledge_state_mutations"][0]["after"]["mastery"] == 0.7
    assert report["recent_followup_runs"] == []
    assert report["agent_flow"][0]["action"] == "practice"
    assert report["profile_versions"][0]["source_attempt_id"] == report["recent_attempts"][0]["attempt_id"]
