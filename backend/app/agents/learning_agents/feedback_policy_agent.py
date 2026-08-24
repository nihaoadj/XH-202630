"""Deterministic P0-07 feedback action and mastery policies."""

from __future__ import annotations

from dataclasses import dataclass

from app.models.feedback.feedback_loop import (
    FeedbackAction,
    FeedbackContext,
    KnowledgeStateMutation,
    KnowledgeStateValue,
    LearningAttempt,
)


@dataclass(frozen=True)
class FeedbackPolicyDecision:
    action: FeedbackAction
    reason_codes: tuple[str, ...]
    target_knowledge_point_ids: tuple[str, ...]
    decision_reason: str
    should_generate: bool


def decide_attempt(attempt: LearningAttempt, context: FeedbackContext) -> FeedbackPolicyDecision:
    """Use auditable thresholds; an individual weak point blocks global advance."""

    weak_points = tuple(
        item.knowledge_point_id
        for item in attempt.knowledge_point_results
        if (item.score or 0.0) < 0.60
    )
    if attempt.overall_score < 0.60 or weak_points:
        codes = ["overall_below_0_60"] if attempt.overall_score < 0.60 else []
        if weak_points:
            codes.append("knowledge_point_blocker_below_0_60")
        return FeedbackPolicyDecision(
            action=FeedbackAction.REMEDIATE,
            reason_codes=tuple(codes),
            target_knowledge_point_ids=weak_points or tuple(
                item.knowledge_point_id for item in attempt.knowledge_point_results
            ),
            decision_reason="总分或至少一个知识点低于 60%，保持当前主路径并激活补救学习。",
            should_generate=True,
        )
    # 0.60 and 0.85 are deliberately inclusive in the practice band.
    if attempt.overall_score <= 0.85:
        return FeedbackPolicyDecision(
            action=FeedbackAction.PRACTICE,
            reason_codes=("overall_between_0_60_and_0_85",),
            target_knowledge_point_ids=tuple(
                item.knowledge_point_id for item in attempt.knowledge_point_results
            ),
            decision_reason="总分处于 60% 到 85% 的强化区间，保持主路径并增加练习。",
            should_generate=False,
        )
    return FeedbackPolicyDecision(
        action=FeedbackAction.ADVANCE,
        reason_codes=("overall_above_0_85",),
        target_knowledge_point_ids=tuple(
            item.knowledge_point_id for item in attempt.knowledge_point_results
        ),
        decision_reason="总分高于 85% 且没有知识点阻断项，可以推进到后继或挑战节点。",
        should_generate=True,
    )


def build_mastery_mutations(
    attempt: LearningAttempt,
    context: FeedbackContext,
) -> list[KnowledgeStateMutation]:
    """Apply an explainable EWMA: new = 0.7 * old + 0.3 * attempt score.

    Duration and hints remain decision/audit features in P0-07; they do not silently
    distort mastery. Replaying an attempt is stopped by repository idempotency before
    this formula can be applied twice.
    """

    mutations: list[KnowledgeStateMutation] = []
    for item in attempt.knowledge_point_results:
        previous = context.knowledge_states.get(item.knowledge_point_id)
        observed = float(item.score or 0.0)
        previous_objective_count = previous.objective_evidence_count if previous else 0
        prior = previous.self_report_prior if previous else None
        if previous_objective_count == 0:
            mastery = observed if prior is None else 0.2 * prior + 0.8 * observed
        else:
            mastery = 0.7 * float(previous.mastery or 0.0) + 0.3 * observed
        mastery = round(float(mastery), 6)
        status = "weak" if mastery < 0.60 else "learning" if mastery <= 0.85 else "mastered"
        objective_count = previous_objective_count + 1
        distinct_count = (previous.distinct_objective_source_count if previous else 0) + 1
        confidence = "high" if objective_count >= 3 and distinct_count >= 2 else "medium"
        after = KnowledgeStateValue(
            mastery=mastery,
            status=status,
            self_report_prior=prior,
            confidence=confidence,
            objective_evidence_count=objective_count,
            distinct_objective_source_count=distinct_count,
            attempt_count=(previous.attempt_count if previous else 0) + 1,
            last_evidence_type="learning_attempt",
            last_evidence_id=attempt.attempt_id,
            last_attempt_id=attempt.attempt_id,
            row_version=(previous.row_version if previous else 0) + 1,
        )
        mutations.append(KnowledgeStateMutation(
            knowledge_point_id=item.knowledge_point_id,
            before=previous,
            after=after,
            source_attempt_id=attempt.attempt_id,
            reason=("prior blend(0.2 * self_report + 0.8 * first objective)"
                    if previous_objective_count == 0 and prior is not None
                    else "first objective score" if previous_objective_count == 0
                    else "EWMA(0.7 * previous + 0.3 * current_attempt); hints/duration excluded"),
        ))
    return mutations
