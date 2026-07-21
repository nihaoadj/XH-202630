import pytest

from app.db.learner.memory import MemoryLearnerRepository
from app.db.learner.repository import create_learner_repository
from app.db.resource.memory import MemoryResourceRepository
from app.db.resource.repository import create_resource_repository
from app.models.schemas import LearnerProfile
from app.services.learner_service import LearnerService
from app.services.feedback_service import FeedbackService
from app.services.report_service import ReportService


def test_learner_service_crud():
    repo = MemoryLearnerRepository()
    service = LearnerService(repo)

    profile = LearnerProfile(
        learner_id="svc_001",
        education="本科",
        major="计算机",
        theory_scores={"A": 80},
        learning_goal="测试",
    )

    service.create_or_update(profile)
    assert service.get("svc_001").major == "计算机"


def test_repository_factories_choose_memory_implementation():
    assert isinstance(create_learner_repository("memory"), MemoryLearnerRepository)
    assert isinstance(create_resource_repository("memory"), MemoryResourceRepository)


def test_feedback_service_downgrade():
    profile = LearnerProfile(
        learner_id="fb_001",
        education="本科",
        major="计算机",
        theory_scores={"A": 80},
        weak_points=[],
        strong_points=[],
        learning_goal="测试",
    )

    service = FeedbackService()
    from app.models.schemas import FeedbackRequest
    req = FeedbackRequest(learner_id="fb_001", resource_id="res_001", correct_rate=0.5, answers=[])
    result = service.process_feedback(profile, req)

    assert result.decision == "降维解释"
    assert profile.skill_level == "初级"


def test_report_service():
    profile = LearnerProfile(
        learner_id="rp_001",
        education="本科",
        major="计算机",
        theory_scores={"工业互联网": 65, "MQTT": 85},
        weak_points=["A"],
        strong_points=["B"],
        learning_goal="测试",
    )

    service = ReportService()
    report = service.build_report(profile)

    assert report["learner_id"] == "rp_001"
    assert len(report["radar"]["dimensions"]) == 2
    assert report["difficulty_curve"][0]["recommended_difficulty"] == "中级"
    assert report["difficulty_curve"][1]["recommended_difficulty"] == "高级"
