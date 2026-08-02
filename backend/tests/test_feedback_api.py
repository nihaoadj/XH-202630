from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import feedback
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.schemas import ExerciseItem, LearnerProfile, LearningResource
from app.services.feedback_service import FeedbackService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService


class _KnowledgeService:
    def load_diagnostic_questions(self, knowledge_base_id):
        return []

    def select_diagnostic_questions(self, knowledge_base_id, limit=None):
        return []


def _app():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="feedback_001",
            learner_type="测试学习者",
            education="本科",
            major="软件工程",
            knowledge_base_id="kb-feedback",
            learning_goal="完成反馈测评闭环",
        )
    )
    resource_repo = MemoryResourceRepository()
    resource_repo.save(
        LearningResource(
            resource_id="res_feedback_001",
            learner_id="feedback_001",
            topic="RAG 基础",
            resource_type="讲义",
            difficulty="初级",
            knowledge_points=["检索", "生成"],
            source_refs=[],
            exercise_items=[
                ExerciseItem(
                    question_id="q1",
                    question="RAG 的 R 指的是什么？",
                    answer="Retrieval",
                    knowledge_point="检索",
                    difficulty="初级",
                ),
                ExerciseItem(
                    question_id="q2",
                    question="RAG 的 G 指的是什么？",
                    answer="Generation",
                    knowledge_point="生成",
                    difficulty="初级",
                ),
            ],
        ),
        "feedback_001",
        "RAG 基础",
    )

    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(resource_repo),
        feedback_service=lambda: FeedbackService(MemoryFeedbackRepository()),
        knowledge_service=lambda: _KnowledgeService(),
    )
    app.include_router(feedback.router, prefix="/api/feedback")
    return TestClient(app), learner_repo


def test_feedback_evaluation_session_and_submit():
    client, learner_repo = _app()

    session_response = client.get("/api/feedback/evaluation/feedback_001/res_feedback_001")
    assert session_response.status_code == 200
    body = session_response.json()
    assert body["total"] == 2
    assert body["questions"][0]["question_id"] == "q1"
    assert "answer" not in body["questions"][0]

    submit_response = client.post(
        "/api/feedback/evaluation/submit",
        json={
            "learner_id": "feedback_001",
            "resource_id": "res_feedback_001",
            "answers": [
                {"question_id": "q1", "answer": "Retrieval"},
                {"question_id": "q2", "answer": "Wrong"},
            ],
            "self_rating": 4,
            "practice_result": {
                "comment": "讲义整体清晰，但生成部分还想多练。",
            },
        },
    )

    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["correct_rate"] == 0.5
    assert result["correct_count"] == 1
    assert result["wrong_knowledge_points"] == ["生成"]
    assert result["feedback"]["decision"] == "降维解释"

    profile = learner_repo.get("feedback_001")
    assert profile is not None
    assert profile.last_feedback_summary["resource_id"] == "res_feedback_001"
