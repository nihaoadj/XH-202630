"""Project the next step from the primary assessment and its frozen repair target."""

from app.models.feedback.rounds import RoundRemediationRecommendationV1
from app.core.learning_tiers import tier_for_level
from app.models.learners.mastery import CurriculumProgressStatus, MASTERY_CONFIRMATION_THRESHOLD, NextGenerationCandidateV1
from app.services.learners.initial_placement import initial_passed_node_ids


def original_node_id(repository, round_id):
    if not round_id:
        return None
    member = repository.one("learning_round_nodes", round_id=round_id, role="primary")
    initial = repository.one("learning_round_stages", round_id=round_id, ordinal=0)
    if not member or not initial:
        return None
    binding = repository.one("learning_round_stage_nodes", stage_id=initial["stage_id"],
                             round_node_id=member["round_node_id"])
    return binding["request_snapshot"].get("remediation_original_node_id") if binding else None


def recommendation(profile, source, repository, mastery, nodes, options=None):
    if source is None:
        return None
    context = source.metadata.get("round_context", {})
    round_id = context.get("round_id")
    rounds = repository.find("learning_rounds", learner_id=profile.learner_id)
    active = max((row for row in rounds if row["protocol_version"] == "learning-round/v1"),
                 key=lambda row: (row["created_at"], row["round_id"]), default=None)
    if not active or active["round_id"] != round_id or active["knowledge_base_id"] != profile.knowledge_base_id:
        return None
    member = repository.one("learning_round_nodes", round_id=round_id, role="primary")
    primary = nodes.get(member["skill_node_id"]) if member else None
    if primary is None:
        return None
    decisions = repository.find("feedback_node_decisions", round_node_id=member["round_node_id"])
    latest = max(decisions, key=lambda row: (row["created_at"], row["node_decision_id"]), default=None)
    if not latest or latest["attempt_id"] != source.attempt_id:
        return None
    if repository.find("learning_rounds", parent_round_id=round_id):
        return None

    original = nodes.get(original_node_id(repository, round_id))
    options = options or mastery.next_generation_options(profile)
    active_tier = options.tier_progress.active_tier if options.tier_progress else tier_for_level(profile.skill_level)
    unlocked_tier = options.tier_progress.highest_unlocked_tier if options.tier_progress else active_tier

    if original and mastery.curriculum_repo:
        if latest["score"] < MASTERY_CONFIRMATION_THRESHOLD:
            return _project("practice_prerequisite", primary, original)
        curriculum = {row.skill_node_id: row for row in mastery.curriculum_repo.list_nodes(
            profile.learner_id, profile.knowledge_base_id,
        )}
        passed = initial_passed_node_ids(profile)
        missing = [node_id for node_id in original.prerequisites
                   if not _satisfied(curriculum.get(node_id), node_id in passed)]
        if missing:
            foundations = mastery.feedback_downgrade_candidates(
                profile, source_node_ids=[original.node_id], maximum_tier=min(original.tier, unlocked_tier),
            )
            return _recommend_prerequisite(foundations, original, active_tier, required=missing)
        if _satisfied(curriculum.get(primary.node_id), False) and original.tier <= unlocked_tier:
            return _project("return_to_original", original, original)
        return None

    if latest["action"] == "remediate":
        foundations = mastery.feedback_downgrade_candidates(profile, source_node_ids=[primary.node_id])
        return _recommend_prerequisite(foundations, primary, active_tier)
    return None


def _satisfied(record, initially_passed):
    if record is None:
        return initially_passed
    return not record.placement_verification_required and (
        record.progress_status == CurriculumProgressStatus.COMPLETED
        or (record.verified_attempt_count == 0 and (record.placement_exempt or initially_passed))
    )


def _recommend_prerequisite(foundations, original, active_tier, *, required=None):
    candidates = [item for item in foundations if required is None or item.skill_node_id in required]
    selected = min(candidates, key=lambda item: (item.tier != active_tier, item.rank), default=None)
    if selected is None:
        return None
    return RoundRemediationRecommendationV1(
        kind="downgrade" if selected.tier < active_tier else "prerequisite",
        node=selected, original_node_name=original.name, original_node_id=original.node_id,
    )


def _project(kind, node, original):
    return RoundRemediationRecommendationV1(
        kind=kind, original_node_name=original.name, original_node_id=original.node_id,
        node=NextGenerationCandidateV1(
            skill_node_id=node.node_id, name=node.name, rank=1, priority_group="learned",
            reason_codes=[kind.upper()], confidence="none", tier=node.tier, tier_label=str(node.tier),
            prerequisite_ids=node.prerequisites,
        ),
    )
