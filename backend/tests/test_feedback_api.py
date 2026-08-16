from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import feedback
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback_loop.memory import MemoryFeedbackLoopRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.schemas import DiagnosticQuestion, ExerciseItem, LearnerProfile, LearningResource
from app.services.feedback_service import FeedbackService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService


class _KnowledgeService:
    def load_diagnostic_questions(self, knowledge_base_id):
        return [
            DiagnosticQuestion(
                question_id="kb_q1",
                knowledge_base_id=knowledge_base_id,
                skill_node_id="skill_retrieval",
                knowledge_point="retrieval",
                question_type="single_choice",
                difficulty="beginner",
                question="Which capability does R represent in RAG?",
                options=["Retrieval", "Ranking", "Routing"],
                answer="Retrieval",
            ),
            DiagnosticQuestion(
                question_id="kb_q2",
                knowledge_base_id=knowledge_base_id,
                skill_node_id="skill_generation",
                knowledge_point="generation",
                question_type="multiple_choice",
                difficulty="beginner",
                question="Which capability does G represent in RAG?",
                options=["Generation", "Grounding", "Graph"],
                answer=["Generation", "Grounding"],
                metadata={"diagnostic_dimension": "scenario"},
            ),
        ]

    def select_diagnostic_questions(self, knowledge_base_id, limit=None):
        questions = self.load_diagnostic_questions(knowledge_base_id)
        return questions[:limit] if limit is not None else questions


def _app():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="feedback_001",
            learner_type="test learner",
            education="undergraduate",
            major="software engineering",
            knowledge_base_id="kb-feedback",
            learning_goal="complete feedback loop",
        )
    )
    resource_repo = MemoryResourceRepository()
    resource_repo.save(
        LearningResource(
            resource_id="res_feedback_001",
            learner_id="feedback_001",
            run_id="run_feedback_001",
            topic="RAG basics",
            resource_type="lecture",
            difficulty="beginner",
            knowledge_points=["retrieval", "generation"],
            source_refs=[],
            learning_path_node="skill_generation",
            publication_status="published",
            exercise_items=[
                ExerciseItem(
                    question_id="q1",
                    question="What does R stand for in RAG?",
                    answer="Retrieval",
                    knowledge_point="retrieval",
                    difficulty="beginner",
                ),
                ExerciseItem(
                    question_id="q2",
                    question="What does G stand for in RAG?",
                    answer="Generation",
                    knowledge_point="generation",
                    difficulty="beginner",
                ),
            ],
        ),
        "feedback_001",
        "RAG basics",
    )

    feedback_service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=MemoryFeedbackLoopRepository(learner_repo),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(resource_repo),
        feedback_service=lambda: feedback_service,
        knowledge_service=lambda: _KnowledgeService(),
    )
    app.include_router(feedback.router, prefix="/api/feedback")
    return TestClient(app), learner_repo


def test_feedback_evaluation_session_and_run_attempt_submit():
    client, learner_repo = _app()

    session_response = client.get("/api/feedback/evaluation/run/feedback_001/run_feedback_001")
    assert session_response.status_code == 200
    body = session_response.json()
    assert body["total"] == 2
    question_by_id = {question["question_id"]: question for question in body["questions"]}
    assert set(question_by_id) == {"kb_q1", "kb_q2"}
    assert body["questions"][0]["question_id"] == "kb_q2"
    assert body["questions"][0]["source"] == "knowledge_base"
    assert all(question["source"] == "knowledge_base" for question in body["questions"])
    assert question_by_id["kb_q1"]["skill_node_id"] == "skill_retrieval"
    assert body["questions"][0]["path_node_id"] == "skill_generation"
    assert "answer" not in body["questions"][0]

    submit_response = client.post(
        "/api/feedback/attempts/run/submit",
        json={
            "learner_id": "feedback_001",
            "run_id": "run_feedback_001",
            "source_resource_id": "res_feedback_001",
            "idempotency_key": "frontend-run-attempt",
            "expected_profile_version": 1,
            "submitted_at": datetime(2026, 8, 13, tzinfo=timezone.utc).isoformat(),
            "answers": [
                {"question_id": "kb_q1", "answer": "Retrieval"},
                {"question_id": "kb_q2", "answer": ["Grounding", "Generation"]},
            ],
        },
    )

    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["attempt"]["overall_score"] == 1.0
    assert result["attempt"]["path_node_id"] is None
    assert result["attempt"]["metadata"]["evaluation_source"] == "knowledge_base"
    trace_by_id = {
        question["question_id"]: question
        for question in result["attempt"]["metadata"]["question_trace"]
    }
    assert trace_by_id["kb_q1"]["skill_node_id"] == "skill_retrieval"
    assert result["attempt"]["metadata"]["question_trace"][0]["path_node_id"] == "skill_generation"
    assert result["attempt"]["metadata"]["point_trace"]["skill_retrieval"]["knowledge_points"] == ["retrieval"]
    assert result["decision"]["action"] == "advance"
    assert result["profile_version"] == 2
    assert {
        item["knowledge_point_id"]
        for item in result["knowledge_state_updates"]
    } == {"skill_retrieval", "skill_generation"}

    attempts_response = client.get("/api/feedback/attempts/feedback_001")
    assert attempts_response.status_code == 200
    assert attempts_response.json()[0]["attempt_id"] == result["attempt"]["attempt_id"]

    profile = learner_repo.get("feedback_001")
    assert profile is not None
    assert profile.profile_version == 2
