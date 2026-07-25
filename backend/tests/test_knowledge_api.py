"""能力图谱、知识库和诊断 API 的契约测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import diagnosis, knowledge, skills
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.models.schemas import DiagnosticAnswerSubmission, DiagnosticSubmitRequest, LearnerProfile
from app.services.diagnosis_service import DiagnosisService
from app.services.knowledge_service import KnowledgeService


def _client() -> tuple[TestClient, KnowledgeService]:
    knowledge_service = KnowledgeService()
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="api_diagnosis_learner",
            learner_type="测试",
            education="本科",
            major="计算机",
            learning_goal="验证 API 诊断闭环",
        )
    )
    diagnosis_service = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        knowledge_service=lambda: knowledge_service,
        diagnosis_service=lambda: diagnosis_service,
    )
    app.include_router(skills.router, prefix="/api/skills")
    app.include_router(diagnosis.router, prefix="/api/diagnosis")
    app.include_router(knowledge.router, prefix="/api/knowledge")
    return TestClient(app), knowledge_service


def test_knowledge_and_diagnosis_endpoints_keep_answers_on_server():
    client, service = _client()

    skills_response = client.get("/api/skills/nodes")
    assert skills_response.status_code == 200
    assert len(skills_response.json()["nodes"]) == 13
    assert skills_response.json()["edges"]
    assert {edge["source"] for edge in skills_response.json()["edges"]} <= {
        node["node_id"] for node in skills_response.json()["nodes"]
    }

    questions_response = client.get("/api/diagnosis/questions?limit=3")
    assert questions_response.status_code == 200
    public_questions = questions_response.json()["questions"]
    assert len(public_questions) == 3
    assert all("answer" not in question and "explanation" not in question for question in public_questions)

    private_questions = service.select_diagnostic_questions(limit=3)
    submit_response = client.post(
        "/api/diagnosis/submit",
        json=DiagnosticSubmitRequest(
            learner_id="api_diagnosis_learner",
            answers=[
                DiagnosticAnswerSubmission(question_id=question.question_id, answer=question.answer)
                for question in private_questions
            ],
        ).model_dump(),
    )
    assert submit_response.status_code == 200
    payload = submit_response.json()
    assert payload["ability_level"] == "进阶"
    assert payload["strong_points"]

    info_response = client.get("/api/knowledge/info")
    assert info_response.status_code == 200
    assert info_response.json()["diagnostic_question_count"] == 39
