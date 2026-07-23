from app.models.schemas import (
    AgentTrace,
    FeedbackDecisionResult,
    FeedbackRecord,
    FeedbackRequest,
    KnowledgeState,
    LearnerProfile,
)


def decide_feedback(
    profile: LearnerProfile,
    req: FeedbackRequest,
    history: list[FeedbackRecord] | None = None,
) -> FeedbackDecisionResult:
    """反馈决策 Agent。

    该 Agent 只负责根据学习反馈输出下一步学习策略，不做 HTTP 处理和数据持久化。
    """
    history = history or []
    error_points = _extract_error_points(req)
    recommended_topics = _recommend_topics(profile, error_points)
    updated_knowledge_states = _build_knowledge_state_updates(profile, req)
    decision, next_action, decision_reason, profile_updates = _decide_strategy(
        profile=profile,
        req=req,
        error_points=error_points,
        history=history,
    )
    regenerate_suggestion = _build_regenerate_suggestion(req, recommended_topics, next_action)

    trace = AgentTrace(
        agent_name="feedback_decision",
        action="学习反馈决策",
        status="success",
        input_summary=(
            f"正确率：{req.correct_rate:.0%}；反馈类型：{req.feedback_type or '未指定'}；"
            f"历史反馈数：{len(history)}"
        ),
        output_summary=f"决策：{decision}；下一步：{next_action}",
        decision_reason=decision_reason,
        evidence_refs=[req.resource_id],
        input_payload={
            "learner_id": req.learner_id,
            "resource_id": req.resource_id,
            "correct_rate": req.correct_rate,
            "answer_count": len(req.answers),
            "history_count": len(history),
        },
        output_payload={
            "decision": decision,
            "next_action": next_action,
            "recommended_topics": recommended_topics,
            "profile_updates": profile_updates,
        },
    )

    return FeedbackDecisionResult(
        decision=decision,
        decision_reason=decision_reason,
        next_action=next_action,
        recommended_topics=recommended_topics,
        updated_knowledge_states=updated_knowledge_states,
        regenerate_suggestion=regenerate_suggestion,
        profile_updates=profile_updates,
        trace=trace,
    )


def apply_feedback_decision(
    profile: LearnerProfile,
    req: FeedbackRequest,
    decision: FeedbackDecisionResult,
) -> LearnerProfile:
    """将反馈 Agent 的决策应用到学习者画像。"""
    for point in decision.profile_updates.get("add_weak_points", []):
        if point and point not in profile.weak_points:
            profile.weak_points.append(point)

    for point, state in decision.updated_knowledge_states.items():
        profile.knowledge_states[point] = state

    if decision.profile_updates.get("skill_level"):
        profile.skill_level = decision.profile_updates["skill_level"]

    profile.last_feedback_summary = {
        "resource_id": req.resource_id,
        "correct_rate": req.correct_rate,
        "decision": decision.decision,
        "next_action": decision.next_action,
        "recommended_topics": decision.recommended_topics,
    }
    return profile


def _decide_strategy(
    profile: LearnerProfile,
    req: FeedbackRequest,
    error_points: list[str],
    history: list[FeedbackRecord],
) -> tuple[str, str, str, dict]:
    repeated_low_scores = _has_repeated_low_scores(history)
    profile_updates: dict = {}

    if req.correct_rate < 0.6:
        weak_points = error_points or [req.resource_id]
        profile_updates = {
            "skill_level": "初级",
            "add_weak_points": weak_points,
        }
        reason = "正确率低于 60%，需要降低难度并补齐前置知识。"
        if repeated_low_scores:
            reason = "连续反馈表现偏低，需要回退到更基础的学习节点并重新生成补救资源。"
        return "降维解释", "regenerate", reason, profile_updates

    if req.correct_rate > 0.85:
        profile_updates = {"skill_level": "高级", "add_weak_points": []}
        return "进阶挑战任务", "challenge", "正确率高于 85%，可以进入更高阶任务。", profile_updates

    profile_updates = {
        "skill_level": profile.skill_level,
        "add_weak_points": error_points,
    }
    return "保持当前难度", "practice", "正确率处于中间区间，建议保持难度并增加针对性练习。", profile_updates


def _extract_error_points(req: FeedbackRequest) -> list[str]:
    points = [
        answer.knowledge_point
        for answer in req.answers
        if not answer.correct and answer.knowledge_point
    ]
    return list(dict.fromkeys([point for point in points if point]))


def _recommend_topics(profile: LearnerProfile, error_points: list[str]) -> list[str]:
    topics = error_points + profile.weak_points
    return list(dict.fromkeys([topic for topic in topics if topic]))[:5]


def _build_knowledge_state_updates(
    profile: LearnerProfile,
    req: FeedbackRequest,
) -> dict[str, KnowledgeState]:
    touched_points = [
        answer.knowledge_point
        for answer in req.answers
        if answer.knowledge_point
    ] or profile.weak_points[:1]

    updates: dict[str, KnowledgeState] = {}
    for point in touched_points:
        if not point:
            continue
        status = "mastered" if req.correct_rate > 0.85 else "weak" if req.correct_rate < 0.6 else "learning"
        updates[point] = KnowledgeState(
            score=req.correct_rate,
            status=status,
            evidence=[req.resource_id],
        )
    return updates


def _build_regenerate_suggestion(
    req: FeedbackRequest,
    recommended_topics: list[str],
    next_action: str,
) -> dict:
    if next_action != "regenerate":
        return {}
    topic = recommended_topics[0] if recommended_topics else req.resource_id
    return {
        "topic": f"{topic} 补救训练",
        "resource_types": ["定制讲义", "分阶测试题"],
        "constraints": {"difficulty": "基础", "must_include_citations": True},
    }


def _has_repeated_low_scores(history: list[FeedbackRecord]) -> bool:
    recent = history[:2]
    return len(recent) >= 2 and all(item.correct_rate < 0.6 for item in recent)
