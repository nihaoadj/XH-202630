"""Learner generation-option projection over the already-read domain facts."""

from __future__ import annotations

from collections.abc import Callable

from app.core.learning_tiers import MAX_TIER, label_for_tier
from app.models.learners.mastery import (
    AbilityMasteryStateV2,
    AbilityStatus,
    CurriculumNodeProgressV1,
    CurriculumProgressStatus,
    CurriculumProgressSummaryV1,
    LearnerTierProgressV1,
    NextGenerationCandidateV1,
    NextGenerationOptionsV1,
)
from app.models.learning_documents.schemas import LearnerProfile, SkillNode


def build_generation_options(
    profile: LearnerProfile,
    *,
    nodes: list[SkillNode],
    names: dict[str, str],
    curriculum_nodes: dict[str, CurriculumNodeProgressV1],
    state_by_id: dict[str, AbilityMasteryStateV2],
    published_counts: dict[str, int],
    exposed: set[str],
    active_tier: int,
    tier_state: LearnerTierProgressV1 | None,
    snapshot_hash: str,
    get_node_tier: Callable[[object], int],
    is_tier_completed: Callable[[], bool],
    curriculum_summary: Callable[[list[CurriculumNodeProgressV1]], CurriculumProgressSummaryV1],
) -> NextGenerationOptionsV1:
    """Project choices; defer the completion read until its original position."""
    downgrade_selection = True

    def prerequisite_blockers(node) -> list[str]:
        blocked: list[str] = []
        for prerequisite in node.prerequisites:
            if prerequisite not in names:
                continue
            record = curriculum_nodes.get(prerequisite)
            prerequisite_tier = next((get_node_tier(item) for item in nodes if item.node_id == prerequisite), None)
            satisfied = bool(record and (
                record.progress_status == CurriculumProgressStatus.COMPLETED
                or (prerequisite_tier is not None and prerequisite_tier < active_tier
                    and record.placement_exempt and not record.placement_verification_required)
            ))
            if not satisfied:
                blocked.append(prerequisite)
        return blocked

    def candidate(node, group: str, rank: int) -> NextGenerationCandidateV1:
        state = state_by_id[node.node_id]
        missing_prerequisites = prerequisite_blockers(node)
        # During downgrade learning the learner is explicitly repairing a
        # prerequisite tier. Every node in that tier is a valid choice;
        # requiring the learner to unlock those same-tier prerequisites in
        # sequence would make the choice UI contradictory to the fallback
        # path and is what caused the disabled-node screen.
        if downgrade_selection and get_node_tier(node) in {active_tier, active_tier - 1}:
            missing_prerequisites = []
        reasons = (
            ["LEARNED_OBJECTIVELY_NOT_MASTERED"]
            if group == "learned_not_mastered"
            else ["ALREADY_EXPOSED"]
            if group == "learned"
            else ["NOT_YET_EXPOSED", "PREREQUISITE_REQUIRED"]
            if missing_prerequisites else ["NOT_YET_EXPOSED"]
        )
        return NextGenerationCandidateV1(
            skill_node_id=node.node_id, name=node.name, priority_group=group,
            rank=rank, reason_codes=reasons, mastery_score=state.mastery_score,
            confidence=state.confidence, prerequisite_ids=list(node.prerequisites),
            blocked_by_node_ids=missing_prerequisites,
            tier=get_node_tier(node), tier_label=label_for_tier(get_node_tier(node)),
            eligibility_status=("placement_exempt" if curriculum_nodes.get(node.node_id, CurriculumNodeProgressV1(
                learner_id=profile.learner_id, knowledge_base_id=profile.knowledge_base_id,
                skill_node_id=node.node_id,
            )).placement_exempt else "blocked" if missing_prerequisites else "available"),
        )

    reinforce_nodes = [
        node for node in nodes
        if get_node_tier(node) == active_tier
        and node.node_id in exposed
        and state_by_id[node.node_id].objective_evidence_count > 0
        and state_by_id[node.node_id].status in {AbilityStatus.WEAK, AbilityStatus.LEARNING}
    ]
    reinforce_nodes.sort(key=lambda node: (
        state_by_id[node.node_id].mastery_score is None,
        state_by_id[node.node_id].mastery_score if state_by_id[node.node_id].mastery_score is not None else 1.0,
        node.node_id,
    ))
    new_nodes = [node for node in nodes if get_node_tier(node) == active_tier and node.node_id not in exposed]
    new_nodes.sort(key=lambda node: (
        -(curriculum_nodes.get(node.node_id).wait_rounds if node.node_id in curriculum_nodes else 0),
        bool(prerequisite_blockers(node)), node.node_id))
    learned_nodes = [node for node in nodes if node.node_id in exposed]
    # A normal learning selection stays inside the active tier. Lower
    # tiers remain visible in mastery/history views, but are not offered
    # as new-tier recommendations after promotion.
    learned_nodes = [node for node in learned_nodes if get_node_tier(node) == active_tier]
    learned_nodes.sort(key=lambda node: (
        state_by_id[node.node_id].status not in {AbilityStatus.WEAK, AbilityStatus.LEARNING},
        state_by_id[node.node_id].mastery_score is None,
        state_by_id[node.node_id].mastery_score if state_by_id[node.node_id].mastery_score is not None else 1.0,
        get_node_tier(node), node.node_id,
    ))
    completed_node_ids = {
        item.skill_node_id for item in curriculum_nodes.values()
        if item.placement_exempt or item.progress_status == CurriculumProgressStatus.COMPLETED
    }
    # A newly unlocked tier must start at the graph frontier. Do not
    # offer every unexposed node in the tier: a node is selectable only
    # when all of its direct prerequisites have been completed.
    next_tier_nodes = [
        node for node in new_nodes
        if node.prerequisites and set(node.prerequisites) <= completed_node_ids
    ]
    if active_tier == 1:
        next_tier_nodes = [node for node in new_nodes if not node.prerequisites]
    learning_nodes = []
    seen_learning_ids: set[str] = set()
    downgrade_nodes = [node for node in nodes if get_node_tier(node) in {active_tier, active_tier - 1}]
    for node in ([*downgrade_nodes] if downgrade_selection else [*next_tier_nodes, *learned_nodes]):
        if node.node_id in seen_learning_ids:
            continue
        seen_learning_ids.add(node.node_id)
        learning_nodes.append(node)
    recommended_reinforcement = [node.node_id for node in reinforce_nodes[:1]]
    recommended_new = [node.node_id for node in next_tier_nodes if not candidate(node, "unlearned", 1).blocked_by_node_ids]
    # Do not use another tier to fill the remaining slots; one or two nodes is valid.
    recommended = [*recommended_reinforcement, *recommended_new[:max(0, 2 - len(recommended_reinforcement))]]
    tier_completed = is_tier_completed()
    cross_new_nodes = []
    cross_review_nodes = []
    cross_high_tiers = {active_tier}
    if tier_completed and tier_state and tier_state.highest_unlocked_tier >= active_tier + 1:
        cross_high_tiers.add(active_tier + 1)
    if tier_state:
        exposed_lower = {
            node_id for node_id, count in published_counts.items()
            if count > 0 and get_node_tier(next(node for node in nodes if node.node_id == node_id)) < active_tier + 1
        }
        for node in nodes:
            node_tier = get_node_tier(node)
            if node_tier not in cross_high_tiers or node.node_id in exposed:
                continue
            ancestors: set[str] = set()
            frontier = list(node.prerequisites)
            while frontier:
                ancestor = frontier.pop()
                if ancestor in ancestors:
                    continue
                ancestors.add(ancestor)
                if ancestor in names:
                    parent = next((item for item in nodes if item.node_id == ancestor), None)
                    if parent:
                        frontier.extend(parent.prerequisites)
            reviews = sorted(
                exposed_lower & ancestors & {
                    item.node_id for item in nodes if get_node_tier(item) == node_tier - 1
                }
            )
            if reviews:
                cross_new_nodes.append(node)
                cross_review_nodes.extend(reviews)
    recommendation_type = (
        "remedial" if tier_state and tier_state.remediation_return_tier else
        "complete" if tier_completed and active_tier == MAX_TIER else
        "advance" if tier_completed else
        "practice" if recommended_reinforcement else "current_tier"
    )
    return NextGenerationOptionsV1(
        learner_id=profile.learner_id, knowledge_base_id=profile.knowledge_base_id,
        profile_version=profile.profile_version, snapshot_hash=snapshot_hash,
        reinforce_weakness=[candidate(node, "learned_not_mastered", index)
                            for index, node in enumerate(reinforce_nodes, start=1)],
        learn_new_knowledge=[candidate(node, "unlearned", index)
                             for index, node in enumerate(next_tier_nodes, start=1)],
        cross_tier_new_knowledge=[candidate(node, "unlearned", index)
                                  for index, node in enumerate(cross_new_nodes, start=1)],
        cross_tier_prerequisite_review=[candidate(
            next(node for node in nodes if node.node_id == node_id), "learned", index,
        ) for index, node_id in enumerate(dict.fromkeys(cross_review_nodes), start=1)],
        learning_candidates=[candidate(
            node,
            "unlearned" if node.node_id not in exposed else "learned",
            index,
        ) for index, node in enumerate(learning_nodes, start=1)],
        recommended_node_ids=recommended[:2],
        curriculum_progress=curriculum_summary(list(curriculum_nodes.values())) if curriculum_nodes else None,
        tier_progress=tier_state, tier_completion=tier_completed,
        recommendation_type=recommendation_type,
    )
