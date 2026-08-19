"""Resource filtering and file download API tests."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import resources
from app.core.file_storage import load_resource_file
from app.db.generation_job.memory import MemoryGenerationJobRepository
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.services.generation_job_service import GenerationJobService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService


def test_resource_filter_and_resource_id_download(monkeypatch):
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="resource_learner",
            learner_type="测试",
            education="本科",
            major="计算机",
            learning_goal="资源接口测试",
        )
    )
    resource_repo = MemoryResourceRepository()
    resource_repo.save(
        LearningResource(
            resource_id="resource_text",
            learner_id="resource_learner",
            topic="RAG",
            resource_type="讲义",
            difficulty="初级",
            run_id="run_recent",
            file_path="data/generated_resources/text/resource_learner/resource_text.md",
            mime_type="text/markdown",
            knowledge_points=["RAG 基础概念"],
            source_refs=[],
            publication_status="published",
        ),
        "resource_learner",
        "RAG",
    )
    resource_repo.save(
        LearningResource(
            resource_id="resource_guide",
            learner_id="resource_learner",
            topic="RAG",
            resource_type="实操指南",
            difficulty="进阶",
            run_id="run_older",
            knowledge_points=[],
            source_refs=[],
            publication_status="published",
        ),
        "resource_learner",
        "RAG",
    )
    resource_repo.save(
        LearningResource(
            resource_id="resource_draft",
            learner_id="resource_learner",
            topic="RAG",
            resource_type="讲义",
            difficulty="初级",
            run_id="run_draft",
            file_path="data/generated_resources/text/resource_learner/resource_draft.md",
            knowledge_points=[],
            source_refs=[],
        ),
        "resource_learner",
        "RAG",
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(resource_repo),
    )
    app.include_router(resources.router, prefix="/api/resources")
    client = TestClient(app)

    listed = client.get("/api/resources/resource_learner?difficulty=初级")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1

    filtered_by_run = client.get("/api/resources/resource_learner?run_id=run_recent")
    assert filtered_by_run.status_code == 200
    assert filtered_by_run.json()["total"] == 1
    assert filtered_by_run.json()["resources"][0]["resource_id"] == "resource_text"

    monkeypatch.setattr(resources, "load_resource_file", lambda _: b"# generated resource")
    downloaded = client.get("/api/resources/file/resource_text")
    assert downloaded.status_code == 200
    assert downloaded.content == b"# generated resource"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert client.get("/api/resources/file/resource_draft").status_code == 404


def test_file_loader_rejects_paths_outside_generated_resources():
    with pytest.raises(ValueError):
        load_resource_file("../.env")


def test_batch_retry_uses_the_explicit_failed_task_request(monkeypatch):
    learner = LearnerProfile(
        learner_id="retry_learner",
        learner_type="测试",
        education="本科",
        major="计算机",
        learning_goal="重试参数验证",
    )
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(learner)
    job_repo = MemoryGenerationJobRepository()

    class _NoopGenerator:
        def generate_with_run_id(self, *_args, **_kwargs):
            class _Response:
                resources = []

            return _Response()

    job_service = GenerationJobService(job_repo, _NoopGenerator())
    first = job_service.create_job(
        learner,
        GenerateRequest(learner_id=learner.learner_id, topic="讲义主题", resource_types=["讲义"]),
        run_id="run_lecture",
    )
    failed = job_service.create_job(
        learner,
        GenerateRequest(
            learner_id=learner.learner_id,
            topic="实操主题",
            resource_types=["实操指南"],
            constraints={"continuation_instructions": "保留实操案例"},
        ),
        run_id="run_guide_failed",
        batch_id=first.batch_id,
    )
    job_repo.mark_failed(failed.run_id, "LLM_OUTPUT_EMPTY")

    monkeypatch.setattr(resources, "build_health_report", lambda _settings: SimpleNamespace(status="ready", error_codes=[]))
    monkeypatch.setattr(resources, "get_settings", lambda: object())
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(MemoryResourceRepository()),
        generation_job_service=lambda: job_service,
    )
    app.include_router(resources.router, prefix="/api/resources")
    client = TestClient(app)

    response = client.post(
        f"/api/resources/batches/{first.batch_id}/continuations",
        json={
            "learner_id": learner.learner_id,
            "resource_types": ["实操指南"],
            "source_run_id": failed.run_id,
        },
    )

    assert response.status_code == 200
    created = job_service.get_job(response.json()["run_id"])
    assert created is not None
    assert created.run_id != failed.run_id
    assert created.batch_id == first.batch_id
    assert created.topic == "实操主题"
    assert created.request_payload["resource_types"] == ["实操指南"]
    assert created.request_payload["constraints"]["continuation_instructions"] == "保留实操案例"
    assert job_service.get_job(failed.run_id).superseded_by_run_id == created.run_id
