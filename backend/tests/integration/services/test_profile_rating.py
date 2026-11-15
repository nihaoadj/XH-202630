"""Current rating follows confirmed primary rounds without changing placement."""

from datetime import timedelta

from app.db.learners.memory import MemoryLearnerRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.profiles import ProfileService
from tests.integration.persistence.test_learning_round_repository import (
    NOW, repository, round_values,  # noqa: F401 (shared memory/SQLite fixture)
)


def add_round(repo, identity, tier, *, learner="learner", kb="kb", day=0, legacy=False):
    with repo.transaction() as tx:
        values = round_values(identity, learner=learner,
                              protocol="legacy-correction/v1" if legacy else "learning-round/v1")
        values.update(knowledge_base_id=kb, created_at=NOW + timedelta(days=day))
        tx.insert("learning_rounds", values)
        for suffix, role, node_tier in [("main", "legacy" if legacy else "primary", tier),
                                        ("review", "legacy" if legacy else "review", 3)]:
            tx.insert("learning_round_nodes", dict(
                round_node_id=f"{identity}-{suffix}", round_id=identity,
                skill_node_id=f"{identity}-{suffix}", role=role, name=suffix, tier=node_tier,
            ))


def profile_repo():
    repo = MemoryLearnerRepository()
    repo.save(LearnerProfile(learner_id="learner", knowledge_base_id="kb", learner_type="test",
                             education="本科", major="test", learning_goal="learn", skill_level="初级"))
    return repo


def test_current_rating_moves_with_primary_and_retains_initial_diagnosis(repository):
    learners = profile_repo()
    service = ProfileService(learners, repository)
    before = learners.get("learner").model_dump()
    initial = service.get("learner")
    assert (initial.skill_level, initial.initial_skill_level, initial.current_skill_level) == ("初级", "初级", "初级")
    assert initial.current_skill_node_id is None
    for identity, tier, level in [("r-a", 2, "中级"), ("r-b", 3, "高级"), ("r-c", 1, "初级")]:
        add_round(repository, identity, tier)
        profile = service.get("learner")
        assert profile.current_skill_level == level
        assert profile.current_skill_node_id == f"{identity}-main"
        assert profile.initial_skill_level == profile.skill_level == "初级"
        listed = service.list_with_pagination(1, 10)["items"][0]
        assert listed.model_dump() == profile.model_dump()
    assert learners.get("learner").model_dump() == before


def test_current_rating_ignores_review_legacy_other_learner_and_other_kb(repository):
    add_round(repository, "old", 2)
    add_round(repository, "legacy", 3, day=1, legacy=True)
    add_round(repository, "other-user", 3, day=2, learner="other")
    add_round(repository, "other-kb", 3, day=3, kb="another")
    profile = ProfileService(profile_repo(), repository).get("learner")
    assert profile.current_skill_level == "中级"
    assert profile.current_skill_node_id == "old-main"
    assert repository.latest_primary_node("other", "kb")["skill_node_id"] == "other-user-main"


def test_rating_falls_back_for_legacy_null_tier_and_optional_repository(repository):
    learners = profile_repo()
    assert ProfileService(learners).get("learner").current_skill_level == "初级"
    add_round(repository, "legacy", 3, legacy=True)
    service = ProfileService(learners, repository)
    assert service.get("learner").current_skill_node_id is None
    add_round(repository, "normal", None, day=1)
    profile = service.get("learner")
    assert profile.current_skill_level == profile.initial_skill_level == "初级"
    assert profile.current_skill_node_id is None
    assert service.get("missing") is None
