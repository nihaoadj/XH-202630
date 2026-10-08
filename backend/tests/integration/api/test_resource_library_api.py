"""Regression tests for the unified learner-facing resource library."""

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.resource_library import library
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService
from app.services.resource_library import ResourceLibraryService


def _text_resource() -> LearningResource:
    return LearningResource(
        resource_id="text-resource",
        learner_id="learner-1",
        topic="RAG",
        resource_type="讲义",
        difficulty="初级",
        run_id="run-1",
        batch_id="batch-1",
        knowledge_points=["RAG 基础"],
        source_refs=[],
        publication_status="published",
    )


def test_resource_library_does_not_require_courseware_service():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(
        LearnerProfile(
            learner_id="learner-1",
            learner_type="测试",
            education="本科",
            major="计算机",
            learning_goal="资源库接口测试",
        )
    )
    resource_repo = MemoryResourceRepository()
    resource_repo.save(_text_resource(), "learner-1", "RAG")

    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learner_repo),
        resource_service=lambda: ResourceService(resource_repo),
    )
    app.include_router(library.router, prefix="/api/resource-library")

    response = TestClient(app).get("/api/resource-library/learner-1")

    assert response.status_code == 200
    assert response.json()[0]["id"] == "text-resource"


def test_resource_library_keeps_text_resources_when_courseware_projection_fails():
    resource_service = ResourceService(MemoryResourceRepository())
    resource_service.repo.save(_text_resource(), "learner-1", "RAG")

    class BrokenCoursewareService:
        def list_library_items(self, learner_id):
            raise RuntimeError("courseware storage unavailable")

    items = ResourceLibraryService(
        resource_service=resource_service,
        courseware_service=BrokenCoursewareService(),
    ).list_by_learner("learner-1")

    assert [item.id for item in items] == ["text-resource"]
