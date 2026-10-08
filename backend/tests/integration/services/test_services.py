import pytest

from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.repository import create_learner_repository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.db.learning_documents.repository import create_resource_repository
from app.agents.learning_agents.feedback_agent import decide_feedback
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.profiles import ProfileService
from app.services.feedback.feedback import FeedbackService
from app.services.reports.reports import ReportService


def test_profile_service_only_saves_existing_profiles():
    repo = MemoryLearnerRepository()
    service = ProfileService(repo)

    profile = LearnerProfile(
        learner_id="svc_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        theory_scores={"A": 80},
        learning_goal="测试",
    )

    assert service.save_existing_profile(profile) is None

    repo.save(profile)
    profile.major = "软件工程"
    service.save_existing_profile(profile)
    assert service.get("svc_001").major == "软件工程"


def test_repository_factories_choose_memory_implementation():
    assert isinstance(create_learner_repository("memory"), MemoryLearnerRepository)
    assert isinstance(create_resource_repository("memory"), MemoryResourceRepository)


def test_feedback_service_downgrade():
    profile = LearnerProfile(
        learner_id="fb_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        theory_scores={"A": 80},
        weak_points=[],
        strong_points=[],
        learning_goal="测试",
    )

    feedback_repo = MemoryFeedbackRepository()
    service = FeedbackService(feedback_repo)
    from app.models.learning_documents.schemas import FeedbackRequest
    req = FeedbackRequest(learner_id="fb_001", resource_id="res_001", correct_rate=0.5, answers=[])
    result = service.process_feedback(profile, req)

    assert result.decision == "降维解释"
    assert profile.skill_level == "初级"
    assert len(service.list_history("fb_001")) == 1


def test_feedback_decision_agent_outputs_next_action():
    from app.models.learning_documents.schemas import FeedbackAnswer, FeedbackRequest

    profile = LearnerProfile(
        learner_id="agent_fb_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        theory_scores={"A": 80},
        weak_points=[],
        strong_points=[],
        learning_goal="测试",
    )
    req = FeedbackRequest(
        learner_id="agent_fb_001",
        resource_id="res_001",
        correct_rate=0.5,
        answers=[
            FeedbackAnswer(
                question_id="q1",
                correct=False,
                knowledge_point="核心概念",
            )
        ],
    )

    result = decide_feedback(profile, req)

    assert result.decision == "降维解释"
    assert result.next_action == "regenerate"
    assert result.recommended_topics == ["核心概念"]
    assert result.trace.agent_name == "feedback_decision"


def test_report_service():
    profile = LearnerProfile(
        learner_id="rp_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        theory_scores={"工业互联网": 65, "MQTT": 85},
        weak_points=["A"],
        strong_points=["B"],
        learning_goal="测试",
    )

    service = ReportService(
        resource_repo=MemoryResourceRepository(),
        feedback_repo=MemoryFeedbackRepository(),
    )
    report = service.build_report(profile)

    assert report["learner_id"] == "rp_001"
    assert isinstance(report["radar"]["dimensions"], list)
    assert report["difficulty_curve"][0]["recommended_difficulty"] == "中级"
    assert report["difficulty_curve"][1]["recommended_difficulty"] == "高级"
