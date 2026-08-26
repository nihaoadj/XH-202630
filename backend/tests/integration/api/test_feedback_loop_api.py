from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.feedback import feedback
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.feedback_loop_memory import MemoryFeedbackLoopRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.feedback.feedback import FeedbackService
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService


def test_client_aggregated_formal_feedback_is_rejected_as_unverified():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="learner",
        learner_type="测试",
        education="本科",
        major="软件工程",
        knowledge_base_id="kb",
        learning_goal="闭环",
    ))
    resources = MemoryResourceRepository()
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
    service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=MemoryFeedbackLoopRepository(learners),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners),
        resource_service=lambda: ResourceService(resources),
        feedback_service=lambda: service,
    )
    app.include_router(feedback.router, prefix="/api/feedback")
    client = TestClient(app)

    response = client.post("/api/feedback/attempts", json={
        "learner_id": "learner",
        "source_resource_id": "resource",
        "source_resource_version": 1,
        "idempotency_key": "frontend-idempotency",
        "expected_profile_version": 1,
        "submitted_at": datetime(2026, 8, 11, tzinfo=timezone.utc).isoformat(),
        "knowledge_point_results": [{
            "knowledge_point_id": "skill-a",
            "question_ids": ["q1"],
            "correct_count": 7,
            "total_count": 10,
        }],
    })
    assert response.status_code == 422
    assert response.json()["detail"] == "FEEDBACK_EVIDENCE_UNVERIFIED"
    assert client.get("/api/feedback/attempts/learner").json() == []
    assert learners.get("learner").profile_version == 1
