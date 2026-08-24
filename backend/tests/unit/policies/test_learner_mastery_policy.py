from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.models.learners.mastery import AbilityEvidenceV1
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.mastery import MasteryService


def _service():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    ))
    nodes = [
        SimpleNamespace(node_id="skill-a", name="A", description=None, level="L1", prerequisites=[], children=["skill-b"]),
        SimpleNamespace(node_id="skill-b", name="B", description=None, level="L2", prerequisites=["skill-a"], children=[]),
    ]
    knowledge = SimpleNamespace(list_skill_nodes=lambda _kb: nodes)
    repository = MemoryMasteryRepository(learner_repo)
    return MasteryService(repository, knowledge), learner_repo


def _evidence(source_type, source_id, score, *, verified, at):
    return AbilityEvidenceV1(
        evidence_id=f"event-{source_id}", learner_id="learner", knowledge_base_id="kb",
        skill_node_id="skill-a", source_type=source_type, source_id=source_id,
        source_hash=(source_id[0] * 64), observed_score=score, verified=verified, occurred_at=at,
    )


def test_prior_first_objective_ewma_confidence_and_replay():
    service, learner_repo = _service()
    names = {"skill-a": "A", "skill-b": "B"}
    now = datetime.now(timezone.utc)
    service.repository.ensure_states("learner", "kb", names)
    service.repository.apply_evidence([
        _evidence("onboarding_self_report", "aaa", 0.25, verified=False, at=now)
    ], names, increment_profile_version=False)
    states, version, changed = service.repository.apply_evidence([
        _evidence("diagnosis", "bbb", 1.0, verified=True, at=now + timedelta(seconds=1))
    ], names, increment_profile_version=True)
    state = next(item for item in states if item.skill_node_id == "skill-a")
    assert (state.mastery_score, state.status.value, state.confidence.value) == (0.85, "learning", "medium")
    assert version == 2 and changed is True

    replay_states, replay_version, replay_changed = service.repository.apply_evidence([
        _evidence("diagnosis", "bbb", 1.0, verified=True, at=now + timedelta(seconds=1))
    ], names, increment_profile_version=True)
    assert replay_changed is False
    assert replay_version == 2
    assert next(item for item in replay_states if item.skill_node_id == "skill-a").objective_evidence_count == 1
    assert learner_repo.get("learner").profile_version == 2

    states, _, _ = service.repository.apply_evidence([
        _evidence("diagnosis", "ccc", 0.0, verified=True, at=now + timedelta(seconds=2)),
        _evidence("learning_attempt", "ddd", 0.0, verified=True, at=now + timedelta(seconds=3)),
    ], names, increment_profile_version=True)
    state = next(item for item in states if item.skill_node_id == "skill-a")
    assert state.mastery_score == 0.4165
    assert state.status.value == "weak"
    assert state.confidence.value == "high"


def test_focus_snapshot_auto_off_and_explicit_are_deterministic():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.ensure_profile_projection(profile)
    auto_a = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    auto_b = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    assert auto_a.mastery_snapshot_hash == auto_b.mastery_snapshot_hash
    assert auto_a.adopted_node_ids == ["skill-a"]
    assert auto_a.ranked_priorities[0].priority_group == "unassessed_prerequisite"

    off = service.focus_snapshot(profile, mode="off", explicit_node_ids=[])
    assert off.adopted_node_ids == []
    assert off.skipped[0].reason_code == "PROFILE_FOCUS_DISABLED"

    explicit = service.focus_snapshot(profile, mode="auto", explicit_node_ids=["skill-b"])
    assert explicit.focus_mode == "explicit"
    assert explicit.adopted_node_ids == ["skill-b"]

