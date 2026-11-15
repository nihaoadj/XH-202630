"""Projection boundaries that matter when persistence and policy are separated."""
from copy import deepcopy
from datetime import datetime, timezone

import pytest

from app.models.learners.mastery import (
    AbilityMasteryStateV2, AbilityStateEventV1, WeaknessPriorityV1,
)
from app.models.learning_documents.schemas import LearnerProfile, SkillNode
from app.services.learners.ability_projection import (
    objective_mastery_history, project_ability_nodes, rank_weakness_priorities,
    select_focus_nodes,
)
from app.services.learners.mastery import MasteryService


def _node(node_id, **kwargs):
    return SkillNode(node_id=node_id, name=node_id, knowledge_base_id="kb", tier=1, **kwargs)


def _state(node_id, **kwargs):
    return AbilityMasteryStateV2(learner_id="learner", knowledge_base_id="kb", skill_node_id=node_id, **kwargs)


def _event(state, score, *, verified=True, source="diagnosis"):
    return AbilityStateEventV1(
        evidence_id=f"e-{state.skill_node_id}-{score}-{source}", learner_id="learner", knowledge_base_id="kb",
        skill_node_id=state.skill_node_id, source_type=source, source_id="fixture", source_hash="a" * 64,
        observed_score=score, verified=verified, after_state=state,
        occurred_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
    )


def _priority(node_id, group, rank):
    return WeaknessPriorityV1(skill_node_id=node_id, rank=rank, priority_group=group,
                             reason_codes=["FIXTURE"], confidence="none")


def test_full_curriculum_group_order_and_cycles_do_not_mutate_input():
    nodes = [_node("w"), _node("r"), _node("n", prerequisites=["unknown"]),
             _node("s", prerequisites=["block"], children=["block"]),
             _node("block", prerequisites=["s"], children=["s"]), _node("m")]
    states = [_state("w", status="weak", mastery_score=0.3, objective_evidence_count=1),
              _state("r", status="learning", mastery_score=0.7), _state("n"),
              _state("s", status="self_reported", self_report_prior=0.2), _state("block"),
              _state("m", status="mastered", mastery_score=0.9)]
    events = [_event(states[1], 0.8), _event(states[1], 0.6)]
    counts = {node.node_id: {"w": 1, "m": 2}.get(node.node_id, 0) for node in nodes}
    before = deepcopy((nodes, states, counts, events))
    ranked = rank_weakness_priorities(nodes, states, counts, events)
    assert [(item.skill_node_id, item.priority_group) for item in ranked] == [
        ("w", "confirmed_weak"), ("r", "regressing_learning"), ("n", "ready_uncovered"),
        ("s", "low_self_report"), ("block", "blocked_uncovered"), ("m", "maintain_mastery"),
    ]
    assert ranked[3].downstream_count == ranked[4].downstream_count == 2
    assert ranked[-1].published_resource_count == 2
    assert (nodes, states, counts, events) == before


def test_zero_unmeasured_and_naive_utc_tie_breaks_are_distinct():
    nodes = [_node("b"), _node("c"), _node("a")]
    states = [_state("b", mastery_score=0, last_updated=datetime(2026, 10, 25, tzinfo=timezone.utc)),
              _state("c"), _state("a", mastery_score=0, last_updated=datetime(2026, 10, 25))]
    ranked = rank_weakness_priorities(nodes, states, {node.node_id: 0 for node in nodes}, [])
    assert [item.skill_node_id for item in ranked] == ["a", "b", "c"]
    assert [item.mastery_score for item in ranked] == [0.0, 0.0, None]


def test_objective_trend_excludes_self_report_and_unmeasured_values():
    zero = _state("a", status="weak", mastery_score=0)
    events = [_event(_state("a", mastery_score=0.2), 0.2),
              _event(zero, 0), _event(_state("a", mastery_score=1), 1, verified=False),
              _event(_state("a", mastery_score=1), 1, source="courseware_self_report"),
              _event(_state("a"), None)]
    history = objective_mastery_history(events)
    assert history == {"a": [0.2, 0.0]}
    projected, summary = project_ability_nodes(
        [_node("a"), _node("b")], [zero, _state("b")], history, [], get_node_tier=lambda _node: 1,
    )
    assert [item.trend_delta for item in projected] == [-0.2, None]
    assert (summary.weak_count, summary.unassessed_count) == (1, 1)


def test_auto_focus_reserves_coverage_and_explicit_focus_has_priority():
    priorities = [_priority("w", "confirmed_weak", 1), _priority("r", "regressing_learning", 2),
                  _priority("n", "ready_uncovered", 3)]
    mode, adopted, skipped = select_focus_nodes(priorities, mode="auto", explicit_node_ids=[])
    assert (mode, adopted) == ("auto", ["w", "n"])
    assert [(item.skill_node_id, item.reason_code) for item in skipped] == [("r", "MAX_FOCUS_NODES_REACHED")]
    mode, adopted, skipped = select_focus_nodes(priorities, mode="off", explicit_node_ids=["n", "n", "r", "w"])
    assert (mode, adopted) == ("explicit", ["n", "r"])
    assert skipped[0].reason_code == "EXPLICIT_TARGETS_SELECTED"
    assert select_focus_nodes([], mode="auto", explicit_node_ids=[])[2][0].reason_code == "NO_ELIGIBLE_WEAKNESS"
    assert select_focus_nodes(priorities, mode="off", explicit_node_ids=[])[1] == []


def test_missing_knowledge_base_does_not_resolve_repositories():
    service = MasteryService(object(), object())
    profile = LearnerProfile(learner_id="learner", learner_type="fixture", education="fixture", major="fixture", learning_goal="fixture")
    assert service.ability_nodes(profile).data_warnings == ["KNOWLEDGE_BASE_UNAVAILABLE"]
    assert service.weakness_priorities(profile) == []
    with pytest.raises(ValueError, match="knowledge base is required"):
        service.focus_snapshot(profile, mode="auto", explicit_node_ids=[])
