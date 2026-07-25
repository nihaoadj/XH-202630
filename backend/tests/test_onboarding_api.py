"""入门问卷创建初始画像与自适应诊断范围测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import diagnosis, onboarding
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.services.diagnosis_service import DiagnosisService
from app.services.knowledge_service import KnowledgeService
from app.services.onboarding_service import OnboardingService


def _client():
    knowledge_service = KnowledgeService()
    learner_repo = MemoryLearnerRepository()
    onboarding_service = OnboardingService(learner_repo, knowledge_service)
    diagnosis_service = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        onboarding_service=lambda: onboarding_service,
        diagnosis_service=lambda: diagnosis_service,
    )
    app.include_router(onboarding.router, prefix="/api/onboarding")
    app.include_router(diagnosis.router, prefix="/api/diagnosis")
    return TestClient(app), learner_repo, knowledge_service


def _questionnaire_payload():
    return {
        "learner_id": "onboarding_001",
        "identity": "在校学生",
        "education": "本科",
        "major": "软件工程",
        "learning_goals": ["了解 RAG 基础概念", "能独立搭建一个 RAG Demo"],
        "python_level": "能写脚本和调用 API",
        "llm_api_level": "调用过 OpenAI 或兼容 API",
        "prompt_level": "会写简单提问",
        "rag_level": "听说过，但说不清流程",
        "known_rag_nodes": ["Embedding", "Rerank"],
        "embedding_screening_answer": "把问题和文档编码为语义向量，再按相似度召回片段",
        "desired_resource_types": ["图解讲义", "一步步实操教程"],
        "learning_modes": ["先讲概念，再做练习"],
        "weekly_time_budget": "2-4 小时",
    }


def test_onboarding_creates_profile_and_only_returns_known_node_questions():
    client, repository, _ = _client()
    response = client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())

    assert response.status_code == 200
    body = response.json()
    assert body["diagnostic_node_ids"] == ["rag_basics", "embedding", "rerank"]
    assert body["screening_results"] == {"embedding": True}
    assert len(body["diagnostic_questions"]) == 9
    assert {question["skill_node_id"] for question in body["diagnostic_questions"]} == set(body["diagnostic_node_ids"])
    assert all("answer" not in question and "explanation" not in question for question in body["diagnostic_questions"])
    assert "chunking" in body["not_started_node_ids"]

    profile = repository.get("onboarding_001")
    assert profile.knowledge_states["Chunk 切分"].status == "not_started"
    assert "Chunk 切分" in profile.weak_points
    assert profile.learning_preferences.metadata["onboarding"]["weekly_time_budget"] == "2-4 小时"
    assert profile.education == "本科"
    assert profile.major == "软件工程"

    questionnaire = client.get("/api/onboarding/questions")
    assert questionnaire.status_code == 200
    screening_question = next(item for item in questionnaire.json()["questions"] if item["question_id"] == "embedding_screening_answer")
    assert screening_question["show_when"] == {"known_rag_nodes_contains": "Embedding"}


def test_diagnosis_keeps_not_started_nodes_after_adaptive_submission():
    client, repository, knowledge_service = _client()
    client.post("/api/onboarding/initial-profile", json=_questionnaire_payload())
    questions = knowledge_service.select_diagnostic_questions(skill_node_ids=["rag_basics", "embedding", "rerank"])
    response = client.post(
        "/api/diagnosis/submit",
        json={
            "learner_id": "onboarding_001",
            "answers": [{"question_id": question.question_id, "answer": question.answer} for question in questions],
        },
    )

    assert response.status_code == 200
    profile = repository.get("onboarding_001")
    assert "Chunk 切分" in profile.weak_points
    assert "Embedding" in profile.strong_points


def test_onboarding_all_unknown_returns_no_diagnostic_questions():
    client, _, _ = _client()
    payload = _questionnaire_payload()
    payload["learner_id"] = "onboarding_002"
    payload["rag_level"] = "完全不了解"
    payload["known_rag_nodes"] = ["都不了解"]

    response = client.post("/api/onboarding/initial-profile", json=payload)
    assert response.status_code == 200
    assert response.json()["diagnostic_node_ids"] == []
    assert response.json()["diagnostic_questions"] == []


def test_wrong_embedding_screening_skips_embedding_diagnostic():
    client, _, _ = _client()
    payload = _questionnaire_payload()
    payload["embedding_screening_answer"] = "把文档按固定字数切分"

    response = client.post("/api/onboarding/initial-profile", json=payload)
    assert response.status_code == 200
    assert response.json()["screening_results"] == {"embedding": False}
    assert "embedding" not in response.json()["diagnostic_node_ids"]
    assert "embedding" in response.json()["not_started_node_ids"]
