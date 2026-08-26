from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.db.learners.curriculum import MemoryCurriculumRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import MemoryTierProgressRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.mastery import MasteryService


def _service(level="中级"):
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn", skill_level=level,
    ))
    nodes = [
        SimpleNamespace(node_id="base", name="基础", description=None, level="零基础", tier=1,
                        prerequisites=[], children=["middle"]),
        SimpleNamespace(node_id="middle", name="应用", description=None, level="Python 基础", tier=2,
                        prerequisites=["base"], children=["advanced"]),
        SimpleNamespace(node_id="middle-two", name="应用二", description=None, level="Python 基础", tier=2,
                        prerequisites=["base"], children=[]),
        SimpleNamespace(node_id="advanced", name="进阶", description=None, level="进阶 RAG", tier=3,
                        prerequisites=["middle"], children=[]),
    ]
    return MasteryService(
        MemoryMasteryRepository(learners),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        curriculum_repo=MemoryCurriculumRepository(),
        tier_progress_repo=MemoryTierProgressRepository(),
    ), learners


def test_middle_placement_exempts_lower_tier_without_objective_mastery():
    service, learners = _service()
    profile = learners.get("learner")
    tier = service.initialize_tier_progress(profile)
    records, _ = service.curriculum_progress(profile)
    states = service.repository.list_states("learner", "kb")

    assert (tier.placement_tier, tier.active_tier, tier.highest_unlocked_tier) == (2, 2, 2)
    assert next(item for item in records if item.skill_node_id == "base").placement_exempt is True
    base_state = next(item for item in states if item.skill_node_id == "base")
    assert base_state.status.value == "self_reported"
    assert base_state.objective_evidence_count == 0


def test_current_tier_never_uses_higher_tier_as_a_three_node_filler():
    service, learners = _service()
    options = service.next_generation_options(learners.get("learner"))
    assert [item.skill_node_id for item in options.learn_new_knowledge] == ["middle", "middle-two"]
    assert all(item.tier == 2 for item in options.learn_new_knowledge)


def test_low_score_targets_direct_lower_tier_prerequisite_and_mixed_targets_fail():
    service, learners = _service()
    profile = learners.get("learner")
    service.initialize_tier_progress(profile)
    targets, tier, return_tier = service.recommend_feedback_targets(
        profile, action="remediate", point_scores={"middle": 0.59},
    )
    assert (targets, tier, return_tier) == (["base"], 1, 2)
    with pytest.raises(ValueError, match="one learning tier"):
        service.validate_generation_targets(profile, ["middle", "advanced"])


def test_low_feedback_only_recommends_prerequisite_and_does_not_auto_downgrade():
    service, learners = _service()
    profile = learners.get("learner")
    service.initialize_tier_progress(profile)

    downgraded = service.apply_tier_feedback(profile, point_scores={"middle": 0.59})
    records, _ = service.curriculum_progress(profile)
    base = next(item for item in records if item.skill_node_id == "base")
    assert downgraded.active_tier == 2
    assert base.placement_exempt is True
    assert base.placement_verification_required is True

    service.curriculum_repo.reconcile_exposure(
        "learner", "kb", {"base": 1}, datetime.now(timezone.utc),
    )
    service.record_curriculum_verification(
        profile, attempt_id="base-formal-attempt", point_scores={"base": 0.8},
        occurred_at=datetime.now(timezone.utc),
    )
    records, _ = service.curriculum_progress(profile)
    base = next(item for item in records if item.skill_node_id == "base")
    assert base.progress_status.value == "completed"
    assert base.placement_exempt is False
    assert base.placement_verification_required is False
    assert service.apply_tier_feedback(profile, point_scores={"base": 0.8}).active_tier == 2
