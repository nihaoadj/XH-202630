from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from app.db.learners.mastery import MemoryMasteryRepository
from app.db.learners.curriculum import MemoryCurriculumRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.tier_progress import MemoryTierProgressRepository
from app.models.learners.mastery import AbilityEvidenceV1, LearnerTierProgressV1
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
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
    return MasteryService(repository, knowledge, curriculum_repo=MemoryCurriculumRepository()), learner_repo


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
    assert (state.mastery_score, state.status.value, state.confidence.value) == (0.85, "mastered", "low")
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
    assert state.mastery_score == 0.034
    assert state.status.value == "weak"
    assert state.confidence.value == "high"


def test_full_self_report_is_confirmed_by_one_passing_objective_assessment():
    service, _ = _service()
    names = {"skill-a": "A", "skill-b": "B"}
    now = datetime.now(timezone.utc)
    service.repository.ensure_states("learner", "kb", names)
    service.repository.apply_evidence([
        _evidence("onboarding_self_report", "aaa", 1.0, verified=False, at=now)
    ], names, increment_profile_version=False)

    states, _, _ = service.repository.apply_evidence([
        AbilityEvidenceV1(
            evidence_id="event-diagnosis-pass", learner_id="learner", knowledge_base_id="kb",
            skill_node_id="skill-a", source_type="diagnosis", source_id="diagnosis-pass",
            source_hash="b" * 64, observed_score=0.8, verified=True, occurred_at=now + timedelta(seconds=1),
            covered_dimensions=["concept", "scenario", "misconception"],
        )
    ], names, increment_profile_version=True)

    state = next(item for item in states if item.skill_node_id == "skill-a")
    assert state.mastery_score == 0.84
    assert state.status.value == "mastered"
    assert state.confidence.value == "high"
    assert state.objective_evidence_count == 1


def test_onboarding_diagnostic_scope_does_not_write_self_report_mastery():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    questions = {
        "rag_level": {"options": [{
            "value": "做过调优或评测", "self_report_score": 100,
            "diagnostic_scope_add": ["skill-a", "skill-b"],
        }]},
        "known_nodes": {"options": [{"value": "了解 A", "diagnostic_scope_add": ["skill-a"]}]},
    }

    states, _, changed = service.apply_onboarding_answers(
        profile, questions, {"rag_level": "做过调优或评测", "known_nodes": ["了解 A"]},
    )

    assert changed is False
    by_id = {state.skill_node_id: state for state in states}
    assert by_id["skill-a"].mastery_score is None
    assert by_id["skill-a"].status.value == "unassessed"
    assert by_id["skill-b"].mastery_score is None
    assert by_id["skill-b"].status.value == "unassessed"


def test_focus_snapshot_auto_off_and_explicit_are_deterministic():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.ensure_profile_projection(profile)
    auto_a = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    auto_b = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    assert auto_a.mastery_snapshot_hash == auto_b.mastery_snapshot_hash
    assert auto_a.adopted_node_ids == ["skill-a"]
    assert [item.skill_node_id for item in auto_a.ranked_priorities] == ["skill-a", "skill-b"]
    assert auto_a.ranked_priorities[0].priority_group == "ready_uncovered"
    assert auto_a.ranked_priorities[1].priority_group == "blocked_uncovered"

    off = service.focus_snapshot(profile, mode="off", explicit_node_ids=[])
    assert off.adopted_node_ids == []
    assert off.skipped[0].reason_code == "PROFILE_FOCUS_DISABLED"

    explicit = service.focus_snapshot(profile, mode="auto", explicit_node_ids=["skill-b"])
    assert explicit.focus_mode == "explicit"
    assert explicit.adopted_node_ids == ["skill-b"]


def test_curriculum_ranks_every_node_and_advances_coverage_after_publication():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    published_a = LearningResource(
        resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
        difficulty="初级", content_text="content", knowledge_points=["skill-a"],
        source_refs=[], publication_status="published",
    )
    service.resource_repo = SimpleNamespace(list_by_learner=lambda _learner_id: [published_a])
    service.apply_diagnosis(
        profile, {"skill-a": 0.2}, source_id="diagnosis-1", source_hash="a" * 64,
        occurred_at=datetime.now(timezone.utc),
    )

    current = learner_repo.get("learner")
    priorities = service.weakness_priorities(current)
    assert len(priorities) == 2
    assert {item.skill_node_id for item in priorities} == {"skill-a", "skill-b"}
    assert next(item for item in priorities if item.skill_node_id == "skill-a").coverage_status == "covered"
    assert next(item for item in priorities if item.skill_node_id == "skill-b").priority_group == "ready_uncovered"

    focus = service.focus_snapshot(current, mode="auto", explicit_node_ids=[])
    assert focus.adopted_node_ids == ["skill-a", "skill-b"]


def test_next_generation_options_keep_reinforcement_and_new_knowledge_separate():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.resource_repo = SimpleNamespace(list_by_learner=lambda _learner_id: [
        LearningResource(
            resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
            difficulty="初级", content_text="content", knowledge_points=["skill-a"],
            source_refs=[], publication_status="published",
        )
    ])
    service.apply_diagnosis(
        profile, {"skill-a": 0.2}, source_id="diagnosis-1", source_hash="a" * 64,
        occurred_at=datetime.now(timezone.utc),
    )
    current = learner_repo.get("learner")
    options = service.next_generation_options(current)
    assert [item.skill_node_id for item in options.reinforce_weakness] == ["skill-a"]
    # The L2 node is deliberately hidden: an incomplete L1 batch cannot be
    # filled with a higher-tier node.
    assert options.learn_new_knowledge == []
    assert options.reinforce_weakness[0].priority_group == "learned_not_mastered"
    assert [item.skill_node_id for item in options.learning_candidates] == ["skill-a"]
    assert options.learning_candidates[0].priority_group == "learned"

    _, selected = service.confirm_next_generation_intent(
        current, intent="reinforce_weakness", selected_node_ids=["skill-a"],
        snapshot_hash=options.snapshot_hash,
    )
    assert selected == ["skill-a"]
    with pytest.raises(ValueError):
        service.confirm_next_generation_intent(
            current, intent="reinforce_weakness", selected_node_ids=["skill-b"],
            snapshot_hash=options.snapshot_hash,
        )


def test_unlocked_tier_only_recommends_completed_nodes_direct_successors():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    ))
    nodes = [
        SimpleNamespace(node_id="root-a", name="根节点 A", tier=1, prerequisites=[], children=[]),
        SimpleNamespace(node_id="root-b", name="根节点 B", tier=1, prerequisites=[], children=[]),
        SimpleNamespace(node_id="root-c", name="根节点 C", tier=1, prerequisites=[], children=[]),
        SimpleNamespace(node_id="next-a", name="后继节点 A", tier=2, prerequisites=["root-a"], children=[]),
        SimpleNamespace(node_id="next-b", name="后继节点 B", tier=2, prerequisites=["root-b"], children=[]),
        SimpleNamespace(node_id="blocked", name="更后继节点", tier=2, prerequisites=["next-a"], children=[]),
    ]
    learner = learner_repo.get("learner")
    resources = [LearningResource(
        resource_id=f"published-{node_id}", learner_id="learner", topic="topic", resource_type="讲义",
        difficulty="初级", content_text="content", knowledge_points=[node_id],
        source_refs=[], publication_status="published",
    ) for node_id in ("root-a", "root-b", "root-c")]
    service = MasteryService(
        MemoryMasteryRepository(learner_repo),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        resource_repo=SimpleNamespace(list_by_learner=lambda _learner_id: resources),
        curriculum_repo=MemoryCurriculumRepository(),
        tier_progress_repo=MemoryTierProgressRepository(),
    )
    service.tier_progress_repo.save(LearnerTierProgressV1(
        learner_id="learner", knowledge_base_id="kb", placement_tier=1,
        active_tier=2, highest_unlocked_tier=2, profile_version=learner.profile_version,
    ))
    service.record_curriculum_verification(
        learner, attempt_id="attempt-root-a",
        point_scores={"root-a": 1.0, "root-b": 1.0, "root-c": 1.0},
        occurred_at=datetime.now(timezone.utc),
    )

    options = service.next_generation_options(learner)

    assert [item.skill_node_id for item in options.learn_new_knowledge] == ["next-a", "next-b"]
    _, selected = service.confirm_next_generation_intent(
        learner, intent="upgrade_learning", selected_node_ids=["next-a"],
        snapshot_hash=options.snapshot_hash,
    )
    assert selected == ["next-a"]



def test_downgrade_intent_only_accepts_current_feedback_tier_candidates():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.tier_progress_repo = MemoryTierProgressRepository()
    service.tier_progress_repo.save(LearnerTierProgressV1(
        learner_id="learner", knowledge_base_id="kb", placement_tier=2,
        active_tier=1, highest_unlocked_tier=2, remediation_return_tier=2,
        profile_version=profile.profile_version,
    ))
    service.resource_repo = SimpleNamespace(list_by_learner=lambda _learner_id: [
        LearningResource(
            resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
            difficulty="初级", content_text="content", knowledge_points=["skill-a"],
            source_refs=[], publication_status="published",
        )
    ])
    options = service.next_generation_options(profile)
    assert options.recommendation_type == "remedial"
    assert [item.skill_node_id for item in options.learning_candidates] == ["skill-a"]

    _, selected = service.confirm_next_generation_intent(
        profile, intent="downgrade_learning", selected_node_ids=["skill-a"],
        snapshot_hash=options.snapshot_hash,
    )
    assert selected == ["skill-a"]
    # Returning to an unselected feedback report later must not make the
    # previously offered path expire merely because its UI snapshot changed.
    _, selected_after_reload = service.confirm_next_generation_intent(
        profile, intent="downgrade_learning", selected_node_ids=["skill-a"],
        snapshot_hash="0" * 64,
    )
    assert selected_after_reload == ["skill-a"]
    _, selected_without_snapshot = service.confirm_next_generation_intent(
        profile, intent="downgrade_learning", selected_node_ids=["skill-a"],
    )
    assert selected_without_snapshot == ["skill-a"]
    with pytest.raises(ValueError):
        service.confirm_next_generation_intent(
            profile, intent="downgrade_learning", selected_node_ids=["skill-b"],
            snapshot_hash=options.snapshot_hash,
        )


def test_curriculum_uses_published_exposure_to_reach_all_nodes_in_order():
    learner_repo = MemoryLearnerRepository()
    learner_repo.save(LearnerProfile(
        learner_id="learner", learner_type="test", education="本科", major="软件",
        knowledge_base_id="kb", learning_goal="learn",
    ))
    nodes = [
        SimpleNamespace(node_id="skill-a", name="A", description=None, level="L1", prerequisites=[], children=["skill-b"]),
        SimpleNamespace(node_id="skill-b", name="B", description=None, level="L2", prerequisites=["skill-a"], children=["skill-c"]),
        SimpleNamespace(node_id="skill-c", name="C", description=None, level="L3", prerequisites=["skill-b"], children=[]),
    ]
    published: list[LearningResource] = []
    service = MasteryService(
        MemoryMasteryRepository(learner_repo),
        SimpleNamespace(list_skill_nodes=lambda _kb: nodes),
        SimpleNamespace(list_by_learner=lambda _learner_id: published),
    )
    profile = learner_repo.get("learner")

    assert service.focus_snapshot(profile, mode="auto", explicit_node_ids=[]).adopted_node_ids == ["skill-a"]
    published.append(LearningResource(
        resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
        difficulty="初级", content_text="content", knowledge_points=["A"],
        source_refs=[], publication_status="published",
    ))
    second_round = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    assert second_round.adopted_node_ids == ["skill-b"]
    assert len(second_round.adopted_node_ids) <= 3

    published.append(LearningResource(
        resource_id="published-b", learner_id="learner", topic="topic", resource_type="讲义",
        difficulty="初级", content_text="content", knowledge_points=["skill-b"],
        source_refs=[], publication_status="published",
    ))
    third_round = service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
    assert third_round.adopted_node_ids == ["skill-c"]
    assert [item.skill_node_id for item in third_round.ranked_priorities] == [
        "skill-c", "skill-a", "skill-b",
    ]


def test_curriculum_persists_all_nodes_wait_debt_and_verified_transitions():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.schedule_generation(profile, run_id="run-1", selected_node_ids=["skill-a"])
    nodes, summary = service.curriculum_progress(profile)
    by_id = {item.skill_node_id: item for item in nodes}
    assert summary.total_count == 2
    assert by_id["skill-a"].progress_status.value == "scheduled"
    assert by_id["skill-b"].wait_rounds == 0  # It is blocked by skill-a, so has no debt.

    published = LearningResource(
        resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
        difficulty="初级", content_text="content", knowledge_points=["skill-a"],
        source_refs=[], publication_status="published",
    )
    service.resource_repo = SimpleNamespace(list_by_learner=lambda _learner_id: [published])
    nodes, _ = service.curriculum_progress(profile)
    by_id = {item.skill_node_id: item for item in nodes}
    assert by_id["skill-a"].progress_status.value == "exposed"
    assert by_id["skill-a"].published_resource_count == 1

    service.record_curriculum_verification(
        profile, attempt_id="attempt-1", point_scores={"skill-a": 0.8},
        occurred_at=datetime.now(timezone.utc),
    )
    nodes, summary = service.curriculum_progress(profile)
    by_id = {item.skill_node_id: item for item in nodes}
    assert by_id["skill-a"].progress_status.value == "completed"
    assert by_id["skill-a"].verified_attempt_count == 1
    assert summary.completed_count == 1


def test_preview_tier_unlock_includes_the_current_passing_assessment():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    service.knowledge_service = SimpleNamespace(list_skill_nodes=lambda _kb: [
        SimpleNamespace(node_id="skill-a", name="A", description=None, level="L1", prerequisites=[], children=[]),
        SimpleNamespace(node_id="skill-b", name="B", description=None, level="L1", prerequisites=[], children=[]),
    ])
    service.tier_progress_repo = MemoryTierProgressRepository()
    service.tier_progress_repo.save(LearnerTierProgressV1(
        learner_id="learner", knowledge_base_id="kb", placement_tier=1,
        active_tier=1, highest_unlocked_tier=1, profile_version=profile.profile_version,
    ))
    published = [
        LearningResource(
            resource_id="published-a", learner_id="learner", topic="topic", resource_type="讲义",
            difficulty="初级", content_text="content", knowledge_points=["skill-a"],
            source_refs=[], publication_status="published",
        ),
        LearningResource(
            resource_id="published-b", learner_id="learner", topic="topic", resource_type="讲义",
            difficulty="初级", content_text="content", knowledge_points=["skill-b"],
            source_refs=[], publication_status="published",
        ),
    ]
    service.resource_repo = SimpleNamespace(list_by_learner=lambda _learner_id: published)
    service.record_curriculum_verification(
        profile, attempt_id="attempt-a", point_scores={"skill-a": 0.8},
        occurred_at=datetime.now(timezone.utc),
    )

    assert service.preview_tier_unlock(profile, point_scores={"skill-b": 0.8}) == (1, 2)
    service.record_curriculum_verification(
        profile, attempt_id="attempt-b", point_scores={"skill-b": 0.8},
        occurred_at=datetime.now(timezone.utc),
    )
    updated = service.apply_tier_feedback(profile, point_scores={"skill-b": 0.8})
    assert updated.active_tier == 2
    assert updated.highest_unlocked_tier == 2


def test_tier_feedback_does_not_auto_return_from_recommendation_at_eighty_percent():
    service, learner_repo = _service()
    profile = learner_repo.get("learner")
    tier_repo = MemoryTierProgressRepository()
    service.tier_progress_repo = tier_repo
    tier_repo.save(LearnerTierProgressV1(
        learner_id="learner", knowledge_base_id="kb", placement_tier=2,
        active_tier=1, highest_unlocked_tier=2, remediation_return_tier=2,
        profile_version=profile.profile_version,
    ))

    updated = service.apply_tier_feedback(profile, point_scores={"skill-a": 0.8})

    assert updated is not None
    assert updated.active_tier == 1
    assert updated.remediation_return_tier == 2
