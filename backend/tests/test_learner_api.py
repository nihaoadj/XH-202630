"""学习者画像的分页、部分更新与删除接口测试。"""
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import learner
from app.db.learner.memory import MemoryLearnerRepository
from app.models.schemas import LearnerProfile
from app.services.learner_service import LearnerService


def test_learner_list_patch_and_delete_endpoints():
    repository = MemoryLearnerRepository()
    service = LearnerService(repository)
    for learner_id, skill_level in [("learner_a", "初级"), ("learner_b", "中级")]:
        repository.save(
            LearnerProfile(
                learner_id=learner_id,
                learner_type="测试",
                education="本科",
                major="计算机",
                skill_level=skill_level,
                learning_goal="接口测试",
            )
        )
    app = FastAPI()
    app.container = SimpleNamespace(learner_service=lambda: service)
    app.include_router(learner.router, prefix="/api/learner")
    client = TestClient(app)

    listed = client.get("/api/learner/list?skill_level=中级")
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["learner_id"] == "learner_b"

    updated = client.patch("/api/learner/profile/learner_a", json={"skill_level": "进阶", "weak_points": ["Rerank"]})
    assert updated.status_code == 200
    assert updated.json()["updated_fields"] == ["skill_level", "weak_points"]
    assert repository.get("learner_a").skill_level == "进阶"

    assert client.delete("/api/learner/profile/learner_a").status_code == 200
    assert client.get("/api/learner/profile/learner_a").status_code == 404
