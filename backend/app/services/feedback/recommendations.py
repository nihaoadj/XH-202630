"""Pure next-step and correction projections for learning feedback."""

from __future__ import annotations

from collections.abc import Callable
from app.models.feedback.feedback_loop import FeedbackLoopResult, CorrectionPackageOptionV1
from app.models.learners.mastery import LearningIntent
from app.models.learning_documents.schemas import LearnerProfile


def _correction_target_ids(result: FeedbackLoopResult) -> list[str]:
    """Keep a review pack available for any non-perfect assessed attempt.

    The pack remains scoped to the knowledge points covered by this attempt;
    it is not a generic remediation selector. A perfect attempt has no
    correction target and therefore does not expose this option.
    """
    attempt_results = list(result.attempt.knowledge_point_results)
    if attempt_results:
        non_perfect_results = [
            item for item in attempt_results if (item.score or 0.0) < 1.0
        ]
        if not non_perfect_results:
            return []
        ordered = sorted(
            non_perfect_results,
            key=lambda item: ((item.score if item.score is not None else 0.0), item.knowledge_point_id),
        )
        return list(dict.fromkeys(item.knowledge_point_id for item in ordered))[:2]
    # Preserve legacy attempts that predate per-point results. Their
    # feedback decision remains the only durable scope available.
    return list(dict.fromkeys(result.decision.target_knowledge_point_ids))[:2]


def _correction_package_option(
    generation_options,
    profile: LearnerProfile | None,
    result: FeedbackLoopResult,
    *,
    correction_target_ids: Callable,
) -> CorrectionPackageOptionV1 | None:
    if generation_options is None:
        return None
    # Correction is scoped to the node(s) assessed in this attempt. The
    # feedback decision may rewrite its targets to lower-tier prerequisites
    # for downgrade learning; those must never become review-pack targets.
    target_ids = correction_target_ids(result)
    if not target_ids:
        return None
    difficulty = profile.skill_level if profile and profile.skill_level in {"初级", "中级", "高级"} else "中级"
    candidate_by_id = {
        item.skill_node_id: item
        for item in getattr(generation_options, "learning_candidates", [])
    }
    candidate_by_id.update({
        item.skill_node_id: item
        for item in generation_options.reinforce_weakness
    })
    candidate_by_id.update({
        item.skill_node_id: item
        for item in generation_options.learn_new_knowledge
    })
    serialized = []
    for point_id in target_ids:
        item = candidate_by_id.get(point_id)
        payload = item.model_dump(mode="json") if item is not None else {
            "skill_node_id": point_id,
            "name": point_id,
            "mastery_score": next(
                (attempt_item.score for attempt_item in result.attempt.knowledge_point_results
                 if attempt_item.knowledge_point_id == point_id),
                None,
            ),
        }
        payload.update({
            "skill_node_id": point_id,
            "priority_group": "correction_target",
            "reason_codes": ["CURRENT_FEEDBACK_TARGET"],
        })
        serialized.append(payload)
    return CorrectionPackageOptionV1(
        eligible=True, selectable_targets=serialized,
        recommended_target_ids=target_ids,
        recommended_difficulty=difficulty, snapshot_hash=generation_options.snapshot_hash,
    )


def _next_step_recommendation(
    result: FeedbackLoopResult,
    generation_options,
    correction_option: CorrectionPackageOptionV1 | None,
    downgrade_candidates: list | None = None,
    tier_unlock: tuple[int, int] | None = None,
) -> dict[str, object]:
    """Return an explainable default without taking the next step for the learner."""
    if generation_options is None:
        return {"recommended_action": "review_feedback", "title": "先回顾本次反馈"}
    new_nodes = [item for item in generation_options.learn_new_knowledge if not item.blocked_by_node_ids]
    review_nodes = list(generation_options.reinforce_weakness)
    action = result.decision.action.value
    learning_candidates = list(getattr(generation_options, "learning_candidates", []))
    learning_candidate_by_id = {item.skill_node_id: item for item in learning_candidates}
    default_learning_ids = [
        node_id for node_id in getattr(
            generation_options, "recommended_node_ids", []
        )
        if node_id in learning_candidate_by_id
        and not learning_candidate_by_id[node_id].blocked_by_node_ids
    ][:2]
    if not default_learning_ids:
        default_learning_ids = [
            item.skill_node_id for item in learning_candidates
            if not item.blocked_by_node_ids
        ][:2]
    if tier_unlock:
        from_tier, to_tier = tier_unlock
        return {
            "recommended_action": "upgrade_learning",
            "learning_mode": "upgrade_learning",
            "learning_intent": LearningIntent.UPGRADE_LEARNING.value,
            "title": f"已解锁第 {to_tier} 阶：升阶学习",
            "description": (
                f"恭喜你，已完成第 {from_tier} 阶全部能力节点，"
                f"现已解锁第 {to_tier} 阶学习。下一步可以选择第 {to_tier} 阶节点继续学习。"
            ),
            "default_learning_node_ids": default_learning_ids,
            "default_new_node_ids": default_learning_ids,
            "default_review_node_ids": [],
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "remediate" and downgrade_candidates:
        default_learning_ids = [
            item.skill_node_id for item in downgrade_candidates
            if not item.blocked_by_node_ids
        ][:2]
        return {
            "recommended_action": "downgrade_learning",
            "learning_mode": "downgrade_learning",
            "learning_intent": LearningIntent.DOWNGRADE_LEARNING.value,
            "title": "默认建议：降阶学习",
            "description": "本次建议来自本轮学习目标的未掌握前置链：可选同阶前置、低阶前置及其前置；系统优先推荐距离目标最近的节点。仅确认低阶节点后才会调整当前学习阶。",
            "default_learning_node_ids": default_learning_ids,
            "default_new_node_ids": default_learning_ids,
            "default_review_node_ids": [],
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "advance" and getattr(generation_options, "recommendation_type", None) == "advance":
        return {
            "recommended_action": "upgrade_learning",
            "learning_mode": "upgrade_learning",
            "learning_intent": LearningIntent.UPGRADE_LEARNING.value,
            "title": "默认建议：升阶学习",
            "description": "优先学习当前所在阶的下一高阶节点，也可以搭配已经学习过的节点；这里只提供建议，不会自动生成。",
            "default_learning_node_ids": default_learning_ids,
            "default_new_node_ids": default_learning_ids,
            "default_review_node_ids": [],
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "remediate" and new_nodes:
        decision_ids = set(result.decision.target_knowledge_point_ids)
        downgrade_nodes = [item for item in new_nodes if item.skill_node_id in decision_ids]
        default_nodes = (downgrade_nodes or new_nodes)[:2]
        return {
            "recommended_action": "learn_new", "learning_intent": LearningIntent.LEARN_NEW_KNOWLEDGE.value,
            "title": "默认建议：补强学习",
            "description": "当前没有可用的降级学习候选，请从当前阶的可学节点中继续补强；纠错包仍可用于本次错题复习。",
            "default_new_node_ids": [item.skill_node_id for item in default_nodes],
            "default_review_node_ids": [],
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "practice" and correction_option and correction_option.eligible:
        alternative_intent = None
        alternative_node_ids = []
        alternative_new_node_ids = []
        alternative_review_node_ids = []
        alternative_title = None
        alternative_description = None
        alternative = {
            "alternative_action": "learn_new_and_reinforce" if new_nodes and review_nodes else "learn_new" if new_nodes else None,
        }
        if downgrade_candidates:
            downgrade_ids = [
                item.skill_node_id for item in downgrade_candidates
                if not item.blocked_by_node_ids
            ][:2]
            alternative = {
                "alternative_action": "downgrade_learning",
            }
            alternative_intent = LearningIntent.DOWNGRADE_LEARNING.value
            alternative_node_ids = downgrade_ids
            alternative_title = "降阶学习"
            alternative_description = "从本轮目标的未掌握前置链补基础，可选同阶前置、低阶前置及其前置；只有确认低阶节点后才会调整当前学习阶。"
        elif new_nodes and review_nodes:
            alternative_intent = LearningIntent.LEARN_NEW_AND_REINFORCE.value
            alternative_new_node_ids = [new_nodes[0].skill_node_id]
            alternative_review_node_ids = [review_nodes[0].skill_node_id]
            alternative_node_ids = alternative_new_node_ids + alternative_review_node_ids
            alternative_title = "一新一旧学习"
            alternative_description = "兼顾推进与巩固：学习一个新节点，同时复习一个已学习但未完全掌握的节点。"
        elif new_nodes:
            alternative_intent = LearningIntent.LEARN_NEW_KNOWLEDGE.value
            alternative_node_ids = [new_nodes[0].skill_node_id]
            alternative_title = "学习新节点"
            alternative_description = "从当前学习阶的可学节点中选择一个继续推进。"
        if alternative_intent:
            alternative.update({
                "alternative_learning_intent": alternative_intent,
                "alternative_learning_node_ids": alternative_node_ids,
                "alternative_new_node_ids": alternative_new_node_ids,
                "alternative_review_node_ids": alternative_review_node_ids,
                "alternative_learning_title": alternative_title,
                "alternative_learning_description": alternative_description,
            })
        return {
            "recommended_action": "correction_package",
            "title": "默认建议：纠错包巩固",
            "description": (
                "本轮处于强化区间，默认先用纠错包巩固本次薄弱点；你也可以选择降阶学习补齐前置。"
                if downgrade_candidates else
                "本轮处于强化区间，默认先用纠错包巩固本次薄弱点；也可以从当前学习阶选择可学习节点。"
            ),
            "default_new_node_ids": [],
            "default_review_node_ids": correction_option.recommended_target_ids,
            **alternative,
        }
    if action == "advance" and new_nodes and review_nodes:
        return {
            "recommended_action": "learn_new_and_reinforce", "learning_intent": LearningIntent.LEARN_NEW_AND_REINFORCE.value,
            "title": "默认建议：一旧一新",
            "description": "本轮达到进阶条件，默认同时巩固一个旧节点并学习一个新节点；你也可以改选两个新节点。",
            "default_new_node_ids": [new_nodes[0].skill_node_id],
            "default_review_node_ids": [review_nodes[0].skill_node_id],
            "can_choose_two_new_nodes": len(new_nodes) >= 2,
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "advance" and len(new_nodes) >= 2:
        return {
            "recommended_action": "learn_new", "learning_intent": LearningIntent.LEARN_NEW_KNOWLEDGE.value,
            "title": "默认建议：一个新节点", "description": "本轮没有需要优先巩固的旧节点，默认推荐一个可学习的新节点；你也可以改选两个新节点。",
            "default_new_node_ids": [new_nodes[0].skill_node_id], "default_review_node_ids": [],
            "can_choose_two_new_nodes": True,
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "practice" and new_nodes and review_nodes:
        return {
            "recommended_action": "learn_new_and_reinforce", "learning_intent": LearningIntent.LEARN_NEW_AND_REINFORCE.value,
            "title": "建议一新一旧学习", "description": "兼顾推进与巩固：学习一个新节点，同时复习一个已学习但未完全掌握的节点；也可改选纠错包强化。",
            "default_new_node_ids": [new_nodes[0].skill_node_id],
            "default_review_node_ids": [review_nodes[0].skill_node_id],
            "alternative_action": "correction_package" if correction_option and correction_option.eligible else None,
        }
    if action == "remediate":
        return {
            "recommended_action": "correction_package" if correction_option and correction_option.eligible else "learn_new",
            "title": "默认建议：纠错包巩固" if not new_nodes else "默认建议：降级学习",
            "description": "纠错包始终开放，你可以直接巩固本次失败点；也可以选择低阶节点学习。" if new_nodes else "当前优先使用纠错包巩固本次失败点。",
            "default_new_node_ids": [item.skill_node_id for item in new_nodes[:2]],
            "default_review_node_ids": [item.skill_node_id for item in review_nodes[:2]],
            "alternative_action": "learn_new" if new_nodes else None,
        }
    if new_nodes:
        return {
            "recommended_action": "learn_new", "learning_intent": LearningIntent.LEARN_NEW_KNOWLEDGE.value,
            "title": "建议选择一个新节点", "description": "默认一次学习一个节点，你可以在同阶范围内选择至多两个新节点。",
            "default_new_node_ids": [new_nodes[0].skill_node_id], "default_review_node_ids": [],
        }
    return {
        "recommended_action": "correction_package" if correction_option and correction_option.eligible else "review_feedback",
        "title": "建议复习巩固", "description": "当前没有可推进的新节点，建议先巩固已学习内容。",
        "default_new_node_ids": [], "default_review_node_ids": [item.skill_node_id for item in review_nodes[:2]],
    }
