"""问卷画像 Profiles API 的分页、部分更新与删除接口测试。"""
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learners import profiles
from app.db.learners.memory import MemoryLearnerRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.profiles import ProfileService


def test_learner_list_patch_permissions_and_delete_endpoints():
    repository = MemoryLearnerRepository()
    service = ProfileService(repository)
    for learner_id, skill_level in [("learner_a", "初级"), ("learner_b", "中级")]:
        repository.save(
            LearnerProfile(
                learner_id=learner_id,
                learner_type="测试",
                education="本科",
                major="计算机",
                skill_level=skill_level,
                learning_goal="接口测试",
                created_at=datetime(2026, 8, 21, 9, 30, tzinfo=timezone.utc),
            )
        )
    app = FastAPI()
    app.container = SimpleNamespace(profile_service=lambda: service)
    app.include_router(profiles.router, prefix="/api/profiles")
    client = TestClient(app)

    listed = client.get("/api/profiles/?skill_level=中级")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["learner_id"] == "learner_b"
    assert listed.json()["items"][0]["created_at"].startswith("2026-08-21T09:30:00")

    rejected = client.patch("/api/profiles/learner_a", json={"skill_level": "进阶", "weak_points": ["Rerank"]})
    assert rejected.status_code == 422
    assert rejected.json()["detail"]["code"] == "PROFILE_SYSTEM_FIELD_READ_ONLY"
    assert rejected.json()["detail"]["illegal_fields"] == ["skill_level", "weak_points"]
    assert repository.get("learner_a").skill_level == "初级"

    updated = client.patch("/api/profiles/learner_a", json={"learning_goal": "掌握可靠 RAG"})
    assert updated.status_code == 200
    assert updated.json()["updated_fields"] == ["learning_goal"]
    assert repository.get("learner_a").learning_goal == "掌握可靠 RAG"

    assert client.delete("/api/profiles/learner_a").status_code == 200
    assert client.get("/api/profiles/learner_a").status_code == 404
    assert client.post("/api/profiles/", json={}).status_code == 405
