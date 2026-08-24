"""能力图谱、知识库和诊断 API 的契约测试。"""
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.learners import diagnosis, profiles as profiles_module
from app.api.knowledge import knowledge
from app.api.skills import skills
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.db.knowledge.seed_catalog import load_learning_catalog_seed
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.shared.models import Base
from app.models.learning_documents.schemas import DiagnosticAnswerSubmission, DiagnosticSubmitRequest, LearnerProfile
from app.services.learners.diagnosis import DiagnosisService
from app.services.learners.mastery import MasteryService
from app.services.knowledge.knowledge import KnowledgeService
from tests.paths import KNOWLEDGE_BASE_ROOT


def _client() -> tuple[TestClient, KnowledgeService]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    catalog = KnowledgeCatalogRepository(sessionmaker(bind=engine))
    for domain, track in load_learning_catalog_seed():
        catalog.upsert_knowledge_base(
            {
                "knowledge_base_id": track["knowledge_base_id"],
                "name": track["name"],
                "version": track.get("metadata", {}).get("version") or "test",
                "domain": domain["name"],
                "description": track.get("description"),
                "learner_levels": track.get("difficulty_levels", []),
                "raw_metadata": {},
            }
        )
        catalog.upsert_learning_catalog(domain, track)

    knowledge_service = KnowledgeService(catalog=catalog)
    manifest = load_knowledge_base_manifest()
    questions_path = (
        KNOWLEDGE_BASE_ROOT
        / "rag_engineering_training"
        / "diagnostic_questions.json"
    )
    from app.models.learning_documents.schemas import DiagnosticQuestion

    catalog.upsert_knowledge_base(manifest)
    catalog.upsert_skill_nodes(manifest["skill_nodes"], manifest["knowledge_base_id"])
    catalog.upsert_diagnostic_questions(
        [DiagnosticQuestion(**item) for item in json.loads(questions_path.read_text(encoding="utf-8"))]
    )
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
    mastery_service = MasteryService(MemoryMasteryRepository(learner_repo), knowledge_service)
    diagnosis_service = DiagnosisService(
        knowledge_service=knowledge_service,
        learner_repo=learner_repo,
        diagnosis_repo=MemoryDiagnosisRepository(),
        mastery_service=mastery_service,
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        knowledge_service=lambda: knowledge_service,
        diagnosis_service=lambda: diagnosis_service,
        mastery_service=lambda: mastery_service,
    )
    app.include_router(skills.router, prefix="/api/skills")
    app.include_router(diagnosis.router, prefix="/api/diagnosis")
    app.include_router(knowledge.router, prefix="/api/knowledge")
    return TestClient(app), knowledge_service


def test_knowledge_and_diagnosis_endpoints_keep_answers_on_server():
    client, service = _client()

    directions_response = client.get("/api/knowledge/directions")
    assert directions_response.status_code == 200
    direction_ids = {item["learning_direction_id"] for item in directions_response.json()["directions"]}
    assert "rag_engineering_training" in direction_ids
    assert "demo_industrial_internet" not in direction_ids
    assert "model_evaluation_safety" not in direction_ids
    domains_response = client.get("/api/knowledge/domains")
    assert domains_response.status_code == 200
    domains = domains_response.json()["domains"]
    domain_ids = {domain["domain_id"] for domain in domains}
    assert "ai_application" in domain_ids
    assert "industrial_internet" not in domain_ids
    rag_domain = next(domain for domain in domains if domain["domain_id"] == "ai_application")
    assert any(track["track_id"] == "rag_engineering_training" for track in rag_domain["tracks"])

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
