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
    def load_assessment_questions(self, knowledge_base_id):
        return [
            DiagnosticQuestion(
                question_id="bank_q1",
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
                question_id="bank_q2",
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

    def load_diagnostic_questions(self, knowledge_base_id):
        return []

    def select_assessment_questions(self, knowledge_base_id, skill_node_ids=None, limit=None):
        questions = self.load_assessment_questions(knowledge_base_id)
        if skill_node_ids:
            selected = [question for question in questions if question.skill_node_id in skill_node_ids]
            if selected:
                questions = selected
        return questions[:limit] if limit is not None else questions

    def select_diagnostic_questions(self, knowledge_base_id, limit=None):
        questions = self.load_diagnostic_questions(knowledge_base_id)
        return questions[:limit] if limit is not None else questions


def _app(*, include_resource_exercises=True, tutor_repo=None):
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
            batch_id="batch_feedback_001",
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
                    skill_node_id="skill_retrieval",
                    question="What does R stand for in RAG?",
                    answer="Retrieval",
                    knowledge_point="retrieval",
                    difficulty="beginner",
                ),
                ExerciseItem(
                    question_id="q2",
                    skill_node_id="skill_generation",
                    question="What does G stand for in RAG?",
                    answer="Generation",
                    knowledge_point="generation",
                    difficulty="beginner",
                ),
            ] if include_resource_exercises else [],
        ),
        "feedback_001",
        "RAG basics",
    )

    feedback_service = FeedbackService(
        MemoryFeedbackRepository(),
        feedback_loop_repo=MemoryFeedbackLoopRepository(learner_repo),
        tutor_repo=tutor_repo,
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


class _TutorHintCounter:
    def count_turns(
        self,
        learner_id,
        *,
        source_run_id=None,
        source_batch_id=None,
        context_type=None,
        question_id=None,
        created_before=None,
    ):
        assert learner_id == "feedback_001"
        assert source_run_id is None
        assert source_batch_id == "batch_feedback_001"
        assert context_type == "question_help"
        assert created_before == datetime(2026, 8, 13, tzinfo=timezone.utc)
        if question_id is None:
            return 3
        return {"bank_q1": 2, "bank_q2": 1}.get(question_id, 0)


def test_feedback_evaluation_session_and_run_attempt_submit():
    client, learner_repo = _app()

    session_response = client.get("/api/feedback/evaluation/run/feedback_001/run_feedback_001")
    assert session_response.status_code == 200
    body = session_response.json()
    assert body["total"] == 4
    question_by_id = {question["question_id"]: question for question in body["questions"]}
    assert set(question_by_id) == {"res_feedback_001:q1", "res_feedback_001:q2", "bank_q1", "bank_q2"}
    assert question_by_id["res_feedback_001:q1"]["source"] == "resource"
    assert question_by_id["bank_q1"]["source"] == "assessment_bank"
    assert question_by_id["res_feedback_001:q1"]["skill_node_id"] == "skill_retrieval"
    assert question_by_id["res_feedback_001:q1"]["path_node_id"] == "skill_generation"
    assert "answer" not in question_by_id["res_feedback_001:q1"]

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
                {"question_id": "res_feedback_001:q1", "answer": "Retrieval"},
                {"question_id": "res_feedback_001:q2", "answer": "Generation"},
                {"question_id": "bank_q1", "answer": "Retrieval"},
                {"question_id": "bank_q2", "answer": ["Generation", "Grounding"]},
            ],
        },
    )

    assert submit_response.status_code == 200
    result = submit_response.json()
    assert result["attempt"]["overall_score"] == 1.0
    assert result["attempt"]["path_node_id"] is None
    assert result["attempt"]["metadata"]["evaluation_source"] == "mixed"
    trace_by_id = {
        question["question_id"]: question
        for question in result["attempt"]["metadata"]["question_trace"]
    }
    assert trace_by_id["res_feedback_001:q1"]["skill_node_id"] == "skill_retrieval"
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


def test_feedback_evaluation_falls_back_to_assessment_bank_without_resource_exercises():
    client, _ = _app(include_resource_exercises=False)

    session_response = client.get("/api/feedback/evaluation/run/feedback_001/run_feedback_001")

    assert session_response.status_code == 200
    body = session_response.json()
    assert body["total"] == 2
    assert {question["question_id"] for question in body["questions"]} == {"bank_q1", "bank_q2"}
    assert all(question["source"] == "assessment_bank" for question in body["questions"])
    assert all("answer" not in question for question in body["questions"])


def test_batch_evaluation_uses_resource_batch_and_stably_shuffles_options():
    client, _ = _app(include_resource_exercises=False)

    first_response = client.get("/api/feedback/evaluation/batch/feedback_001/batch_feedback_001")
    second_response = client.get("/api/feedback/evaluation/batch/feedback_001/batch_feedback_001")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    first_body = first_response.json()
    assert first_body["batch_id"] == "batch_feedback_001"
    assert first_body["resource_ids"] == ["res_feedback_001"]
    assert first_body["questions"] == second_response.json()["questions"]

    submit_response = client.post(
        "/api/feedback/attempts/batch/submit",
        json={
            "learner_id": "feedback_001",
            "batch_id": "batch_feedback_001",
            "source_resource_id": "res_feedback_001",
            "idempotency_key": "frontend-batch-attempt",
            "expected_profile_version": 1,
            "submitted_at": datetime(2026, 8, 13, tzinfo=timezone.utc).isoformat(),
            "answers": [
                {"question_id": "bank_q1", "answer": "Retrieval"},
                {"question_id": "bank_q2", "answer": ["Generation", "Grounding"]},
            ],
        },
    )

    assert submit_response.status_code == 200
    assert submit_response.json()["attempt"]["overall_score"] == 1.0
    assert submit_response.json()["attempt"]["metadata"]["session_id"] == "batch_feedback_001"


def test_batch_attempt_uses_server_side_tutor_hint_counts_without_changing_score():
    client, _ = _app(
        include_resource_exercises=False,
        tutor_repo=_TutorHintCounter(),
    )

    response = client.post(
        "/api/feedback/attempts/batch/submit",
        json={
            "learner_id": "feedback_001",
            "batch_id": "batch_feedback_001",
            "source_resource_id": "res_feedback_001",
            "idempotency_key": "server-tutor-hints",
            "expected_profile_version": 1,
            "submitted_at": datetime(2026, 8, 13, tzinfo=timezone.utc).isoformat(),
            "hint_count": 99,
            "answers": [
                {"question_id": "bank_q1", "answer": "Retrieval"},
                {"question_id": "bank_q2", "answer": ["Grounding", "Generation"]},
            ],
        },
    )

    assert response.status_code == 200
    attempt = response.json()["attempt"]
    assert attempt["hint_count"] == 3
    assert attempt["overall_score"] == 1.0
    hints = {
        item["knowledge_point_id"]: item["hint_count"]
        for item in attempt["knowledge_point_results"]
    }
    assert hints == {"skill_retrieval": 2, "skill_generation": 1}


def test_run_evaluation_prefers_generated_questions_from_any_resource_before_bank_fallback():
    service = FeedbackService(MemoryFeedbackRepository())
    profile = LearnerProfile(
        learner_id="priority_learner",
        learner_type="test learner",
        education="undergraduate",
        major="software engineering",
        knowledge_base_id="kb-feedback",
        learning_goal="test evaluation priority",
    )
    resource_without_questions = LearningResource(
        resource_id="resource_without_questions",
        resource_type="lecture",
        difficulty="beginner",
        knowledge_points=["retrieval"],
        source_refs=[],
        learning_path_node="skill_retrieval",
    )
    resource_with_questions = LearningResource(
        resource_id="resource_with_questions",
        resource_type="exercise",
        difficulty="beginner",
        knowledge_points=["generation"],
        source_refs=[],
        learning_path_node="skill_generation",
        exercise_items=[
            ExerciseItem(
                question_id="generated_q1",
                question_type="single_choice",
                question="Generated question",
                options=["A", "B"],
                answer="A",
            )
        ],
    )

    questions, answer_key = service._build_run_question_specs(
        profile,
        [resource_without_questions, resource_with_questions],
        _KnowledgeService(),
    )

    assert {question.question_id for question in questions} == {
        "bank_q1",
        "bank_q2",
        "resource_with_questions:generated_q1",
    }
    assert [question.skill_node_id for question in questions].count("skill_retrieval") == 1
    assert [question.skill_node_id for question in questions].count("skill_generation") == 2
    assert answer_key["resource_with_questions:generated_q1"] == "A"
