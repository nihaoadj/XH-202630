from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.learners import profiles
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.mastery import MasteryService
from app.services.learners.profiles import ProfileService


def test_ability_nodes_api_returns_unassessed_instead_of_fake_zero():
    learners = MemoryLearnerRepository()
    profile = LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    )
    learners.save(profile)
    nodes = [SimpleNamespace(
        node_id="skill-a", name="能力 A", description="desc", level="L1",
        prerequisites=[], children=[],
    )]
    mastery = MasteryService(
        MemoryMasteryRepository(learners),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
    )
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners),
        mastery_service=lambda: mastery,
    )
    app.include_router(profiles.router, prefix="/api/profiles")

    response = TestClient(app).get("/api/profiles/learner/ability-nodes")
    assert response.status_code == 200
    body = response.json()
    assert body["as_of_profile_version"] == 1
    assert body["summary"]["unassessed_count"] == 1
    assert body["nodes"][0]["skill_node_id"] == "skill-a"
    assert body["nodes"][0]["mastery"]["mastery_score"] is None
    assert body["nodes"][0]["mastery"]["confidence"] == "none"

