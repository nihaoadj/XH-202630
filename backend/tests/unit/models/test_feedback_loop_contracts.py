from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.agents.feedback_policy import decide_attempt
from app.models.feedback_loop import (
    FeedbackAction,
    FeedbackContext,
    KnowledgePointAttemptResult,
    LearningAttempt,
    LearningAttemptSubmit,
)


def _attempt(score: float, *, point_score: float | None = None) -> LearningAttempt:
    point_score = score if point_score is None else point_score
    total = 10000
    point = KnowledgePointAttemptResult(
        knowledge_point_id="skill-a",
        question_ids=["q1"],
        correct_count=round(point_score * total),
        total_count=total,
    )
    return LearningAttempt(
        attempt_id="attempt-1",
        request_hash="a" * 64,
        learner_id="learner",
        source_resource_id="resource",
        source_resource_version=1,
        idempotency_key="idempotency-1",
        expected_profile_version=1,
        submitted_at=datetime.now(timezone.utc),
        duration_ms=0,
        hint_count=0,
        overall_score=score,
        knowledge_point_results=[point],
    )


@pytest.mark.parametrize(("score", "action"), [
    (0.00, FeedbackAction.REMEDIATE),
    (0.59, FeedbackAction.REMEDIATE),
    (0.5999, FeedbackAction.REMEDIATE),
    (0.60, FeedbackAction.PRACTICE),
    (0.70, FeedbackAction.PRACTICE),
    (0.85, FeedbackAction.PRACTICE),
    (0.8501, FeedbackAction.ADVANCE),
    (1.00, FeedbackAction.ADVANCE),
])
def test_feedback_thresholds_are_exact(score, action):
    assert decide_attempt(_attempt(score), FeedbackContext(learner_id="learner", profile_version=1)).action == action


def test_weak_knowledge_point_blocks_high_overall_score():
    attempt = _attempt(0.90, point_score=0.20).model_copy(update={"overall_score": 0.90})
    decision = decide_attempt(attempt, FeedbackContext(learner_id="learner", profile_version=1))
    assert decision.action == FeedbackAction.REMEDIATE
    assert "knowledge_point_blocker_below_0_60" in decision.reason_codes


def test_attempt_recomputes_and_rejects_client_score_mismatch():
    with pytest.raises(ValidationError, match="overall_score does not match"):
        LearningAttemptSubmit(
            learner_id="learner",
            source_resource_id="resource",
            idempotency_key="idempotency-1",
            expected_profile_version=1,
            submitted_at=datetime.now(timezone.utc),
            overall_score=0.9,
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id="skill-a",
                question_ids=["q1"],
                correct_count=1,
                total_count=2,
            )],
        )


def test_attempt_accepts_json_safe_learning_reflection_metadata():
    attempt = LearningAttemptSubmit(
        learner_id="learner",
        source_resource_id="resource",
        idempotency_key="reflection-idempotency",
        expected_profile_version=1,
        submitted_at=datetime.now(timezone.utc),
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q1"],
            correct_count=1,
            total_count=1,
        )],
        metadata={
            "learning_reflection": {
                "completed": True,
                "self_rating": 4,
                "difficulty_feeling": "fit",
                "comment": "案例很有帮助",
            },
        },
    )

    assert attempt.metadata["learning_reflection"]["self_rating"] == 4


@pytest.mark.parametrize("payload", [
    {"correct_count": 2, "total_count": 1},
    {"correct_count": 0, "total_count": 0},
    {"correct_count": 0, "total_count": 1, "duration_ms": -1},
    {"correct_count": 0, "total_count": 1, "hint_count": -1},
])
def test_point_result_rejects_invalid_counts_and_metrics(payload):
    with pytest.raises(ValidationError):
        KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q1"],
            **payload,
        )
