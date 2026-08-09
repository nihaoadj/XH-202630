"""资源筛选与安全下载接口测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from app.api import resources
from app.core.file_storage import load_resource_file
from app.db.learner.memory import MemoryLearnerRepository
from app.db.resource.memory import MemoryResourceRepository
from app.models.schemas import LearnerProfile, LearningResource
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService


def test_resource_filter_and_resource_id_download(monkeypatch):
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(learner_id="resource_learner", learner_type="测试", education="本科", major="计算机", learning_goal="资源接口测试"))
    resource_repo = MemoryResourceRepository()
    resource_repo.save(
        LearningResource(
            resource_id="resource_text",
            learner_id="resource_learner",
            topic="RAG",
            resource_type="讲义",
            difficulty="初级",
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
        LearningResource(resource_id="resource_guide", learner_id="resource_learner", topic="RAG", resource_type="实操指南", difficulty="进阶", knowledge_points=[], source_refs=[], publication_status="published"),
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
    monkeypatch.setattr(resources, "load_resource_file", lambda _: b"# generated resource")
    downloaded = client.get("/api/resources/file/resource_text")
    assert downloaded.status_code == 200
    assert downloaded.content == b"# generated resource"
    assert "attachment" in downloaded.headers["content-disposition"]
    assert client.get("/api/resources/file/resource_draft").status_code == 404


def test_file_loader_rejects_paths_outside_generated_resources():
    with pytest.raises(ValueError):
        load_resource_file("../.env")
