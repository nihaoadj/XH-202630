from datetime import datetime, timezone
from types import SimpleNamespace

from app.db.feedback.memory import MemoryFeedbackRepository
from app.models.feedback.feedback_loop import KnowledgePointAttemptResult, LearningAttemptSubmit
from app.services.feedback.feedback import FeedbackService, _round_assessment_score, _weighted_point_scores
from app.db.feedback.feedback_loop_memory import _assessment_metadata


def test_multiple_choice_scoring_awards_partial_credit_and_deducts_wrong_options():
    service = FeedbackService(MemoryFeedbackRepository())

    assert service._answer_score(
        "multiple_choice", ["A", "B"], ["A"], options=["A", "B", "C", "D"]
    ) == 0.5
    assert service._answer_score(
        "multiple_choice", ["A", "B"], ["A", "B", "C"], options=["A", "B", "C", "D"]
    ) == 0.5
    assert service._answer_score(
        "multiple_choice", ["A", "B"], ["A", "C"], options=["A", "B", "C", "D"]
    ) == 0.0
    assert service._answer_score(
        "multiple_choice", ["A", "B"], ["A", "B"], options=["A", "B", "C", "D"]
    ) == 1.0


def test_assessment_scores_use_decimal_half_up_rounding():
    assert _round_assessment_score(6.65) == 6.7
    assert _round_assessment_score(15.0) == 15.0


def test_point_score_uses_question_weights_and_includes_partial_credit():
    assert _weighted_point_scores([
        {"skill_node_id": "skill-a", "score": 0.0, "max_score": 10.0},
        {"skill_node_id": "skill-a", "score": 5.0, "max_score": 20.0},
    ]) == {"skill-a": 1 / 6}


def test_learning_attempt_uses_server_weighted_score_for_feedback_policy():
    attempt = LearningAttemptSubmit(
        learner_id="learner",
        source_resource_id="resource",
        idempotency_key="weighted-score-test",
        expected_profile_version=1,
        submitted_at=datetime.now(timezone.utc),
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q-001", "q-002"],
            correct_count=1,
            total_count=2,
            score=0.75,
        )],
        metadata={"total_score": 75.0, "max_score": 100.0},
    )

    assert attempt.overall_score == 0.75


def test_scoring_audit_disagreement_keeps_server_scored_attempt_eligible_for_mastery():
    attempt = SimpleNamespace(
        attempt_id="attempt",
        source_resource_id="resource",
        metadata={
            "scoring_audit": {"chunking": "double_disagreement"},
            "question_trace": [{"question_id": "q-001", "skill_node_id": "chunking"}],
        },
    )

    metadata = _assessment_metadata(attempt, "chunking")

    assert metadata["scoring_audit_status"] == "double_disagreement"
    assert metadata["evidence_eligible"] is True
