from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.generation import generation as generate
from app.db.audit.memory import MemoryAuditRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation import generation as generation_module
from app.services.generation.jobs import GenerationJobService
from app.services.generation.generation import GenerationService
from app.services.learners.profiles import ProfileService


class _Workflow:
    def invoke(self, state):
        resource = LearningResource(
            resource_id="job-resource",
            resource_type="讲义",
            difficulty="中级",
            content_text="生成完成",
            knowledge_points=["测试"],
            source_refs=[],
            review_status="unreviewed_draft",
        )
        return {
            **state,
            "generated_resources": [resource],
            "review_result": {"decision": "not_requested", "status": "not_requested"},
            "workflow_status": "completed",
            "final_decision": "未审核草稿",
            "trace": [],
        }


def _app(monkeypatch):
    monkeypatch.setattr(
        generation_module,
        "ensure_generation_ready",
        lambda: SimpleNamespace(status="ready", error_codes=[]),
    )
    monkeypatch.setattr(
        generate,
        "build_health_report",
        lambda settings: SimpleNamespace(status="ready", error_codes=[]),
    )
    monkeypatch.setattr(generate, "get_settings", lambda: object())
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="job_001",
            learner_type="测试",
            education="本科",
            major="软件工程",
            learning_goal="验证异步生成任务",
        )
    )
    resource_repo = MemoryResourceRepository()
    audit_repo = MemoryAuditRepository()
    generation_service = GenerationService(resource_repo, _Workflow(), audit_repo)
    generation_job_service = GenerationJobService(MemoryGenerationJobRepository(), generation_service)
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        generation_service=lambda: generation_service,
        generation_job_service=lambda: generation_job_service,
    )
    app.include_router(generate.router, prefix="/api/generate")
    return TestClient(app), resource_repo


def test_create_generation_job_and_query_status(monkeypatch):
    client, resource_repo = _app(monkeypatch)

    response = client.post(
        "/api/generate/jobs",
        json=GenerateRequest(
            learner_id="job_001",
            topic="测试异步生成",
            include_review=False,
            resource_types=["讲义"],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 200
    body = response.json()
    assert body["job_status"] in {"queued", "completed"}
    run_id = body["run_id"]

    status = client.get(f"/api/generate/jobs/{run_id}")
    assert status.status_code == 200
    status_body = status.json()
    assert status_body["job_status"] == "completed"
    assert status_body["resource_ids"] == ["job-resource"]
    stored = resource_repo.get("job-resource")
    assert stored is not None
    assert stored.run_id == run_id


def test_create_generation_job_returns_503_when_dependencies_not_ready(monkeypatch):
    client, _ = _app(monkeypatch)
    monkeypatch.setattr(
        generate,
        "build_health_report",
        lambda settings: SimpleNamespace(
            status="not_ready",
            error_codes=["EMBEDDING_MODEL_UNAVAILABLE", "VECTOR_COLLECTION_MISSING"],
        ),
    )
    monkeypatch.setattr(generate, "get_settings", lambda: object())

    response = client.post(
        "/api/generate/jobs",
        json=GenerateRequest(
            learner_id="job_001",
            topic="测试异步生成",
            include_review=False,
            resource_types=["讲义"],
        ).model_dump(mode="json"),
    )

    assert response.status_code == 503
    assert "EMBEDDING_MODEL_UNAVAILABLE" in response.json()["detail"]
