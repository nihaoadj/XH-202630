from datetime import datetime, timezone

from app.agents.learning_agents.feedback_policy_agent import decide_attempt
from app.models.feedback.feedback_loop import (
    FeedbackContext,
    KnowledgePointAttemptResult,
    LearningAttempt,
    PathMutationType,
    PathNodeType,
)
from app.services.feedback.learning_path_policy import mutate_learning_path


def _attempt(score, attempt_id="attempt", path_node_id=None):
    return LearningAttempt(
        attempt_id=attempt_id,
        request_hash="a" * 64,
        learner_id="learner",
        source_resource_id="resource",
        source_resource_version=1,
        path_node_id=path_node_id,
        idempotency_key=f"key-{attempt_id}",
        expected_profile_version=1,
        submitted_at=datetime.now(timezone.utc),
        duration_ms=0,
        hint_count=0,
        overall_score=score,
        knowledge_point_results=[KnowledgePointAttemptResult(
            knowledge_point_id="skill-a",
            question_ids=["q1"],
            correct_count=round(score * 100),
            total_count=100,
        )],
    )


def test_low_score_inserts_one_reusable_remedial_node():
    attempt = _attempt(0.4, "a1")
    policy = decide_attempt(attempt, FeedbackContext(learner_id="learner", profile_version=1))
    path, mutation = mutate_learning_path(attempt=attempt, decision_id="d1", policy=policy, existing=None)
    assert mutation.mutation_type == PathMutationType.INSERT_REMEDIAL
    assert len([item for item in path.nodes if item.node_type == PathNodeType.REMEDIAL]) == 1

    repeat = _attempt(0.4, "a2")
    repeated_path, repeated = mutate_learning_path(
        attempt=repeat,
        decision_id="d2",
        policy=decide_attempt(repeat, FeedbackContext(learner_id="learner", profile_version=2)),
        existing=path,
    )
    assert repeated.mutation_type == PathMutationType.HOLD
    assert len([item for item in repeated_path.nodes if item.node_type == PathNodeType.REMEDIAL]) == 1


def test_high_score_completes_current_and_unlocks_the_next_node():
    attempt = _attempt(0.4, "a1")
    path, _ = mutate_learning_path(
        attempt=attempt,
        decision_id="d1",
        policy=decide_attempt(attempt, FeedbackContext(learner_id="learner", profile_version=1)),
        existing=None,
    )
    current = next(item for item in path.nodes if item.node_type == PathNodeType.CORE)
    high = _attempt(0.95, "a2", current.node_id)
    advanced, mutation = mutate_learning_path(
        attempt=high,
        decision_id="d2",
        policy=decide_attempt(high, FeedbackContext(learner_id="learner", profile_version=2)),
        existing=path,
        advance_knowledge_point_id="skill-b",
    )
    assert current.node_id in mutation.completed_node_ids
    assert mutation.unlocked_node_ids
    challenge = next(item for item in advanced.nodes if item.node_type == PathNodeType.CHALLENGE)
    assert challenge.knowledge_point_id == "skill-b"


def test_high_score_does_not_create_a_challenge_for_the_completed_node():
    attempt = _attempt(0.95, "a1")

    path, mutation = mutate_learning_path(
        attempt=attempt,
        decision_id="d1",
        policy=decide_attempt(attempt, FeedbackContext(learner_id="learner", profile_version=1)),
        existing=None,
    )

    assert mutation.completed_node_ids
    assert mutation.unlocked_node_ids == []
    assert not any(item.node_type == PathNodeType.CHALLENGE for item in path.nodes)
