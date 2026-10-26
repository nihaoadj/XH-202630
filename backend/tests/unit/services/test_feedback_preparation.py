"""Prepared requests/evidence keep policy and commit boundaries independent."""

from datetime import datetime, timezone

import pytest

from app.db.feedback.memory import MemoryFeedbackRepository
from app.models.feedback.feedback_loop import FeedbackFollowupSelection, FeedbackResourceOption
from app.models.learning_documents.schemas import (
    LearnerProfile, LearningResource, ResourceEvaluationQuestion, RunAttemptSubmitRequest,
)
from app.services.feedback.attempt_evidence import prepare_attempt_evidence
from app.services.feedback.feedback import FeedbackService
from app.services.feedback.followup_plan import build_followup_plan


def _profile():
    return LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件", knowledge_base_id="kb", learning_goal="合成验收")


@pytest.mark.parametrize("claim", [False, True])
def test_followup_plan_preserves_claim_partition_and_starts_a_new_batch(claim):
    selection = FeedbackFollowupSelection(
        learner_id="learner", attempt_id="attempt", option_id="custom-selection",
        resource_types=["复习清单", "讲义"], include_claim_check=claim,
    )
    option = FeedbackResourceOption(
        option_id="custom-selection", title="自选", description="明确选择", resource_types=["讲义"],
        difficulty="中级", target_knowledge_point_ids=["node"],
    )
    plan = build_followup_plan(
        _profile(), selection, option, attempt_id="attempt", decision_id="decision", difficulty="中级",
        selection_type=None, correction_snapshot=None, historical_assessment_questions=[],
        intent_options=None, source_batch_id="source-batch",
    )
    requests = plan.requests(include_claim_check=claim)
    assert [request.resource_types for request in requests] == ([["复习清单"], ["讲义"]] if claim else [["复习清单", "讲义"]])
    assert all(request.include_claim_check == claim for request in requests)
    assert all(request.constraints["feedback_attempt_id"] == "attempt" for request in requests)
    assert all(request.target_skill_nodes == ["node"] for request in requests)
    assert plan.source_batch_id is None
    assert selection.resource_types == ["复习清单", "讲义"]


def test_correction_plan_keeps_source_batch_and_explicit_missing_history():
    selection = FeedbackFollowupSelection(learner_id="learner", attempt_id="attempt", option_id="personalized-correction-package-v1")
    option = FeedbackResourceOption(
        option_id=selection.option_id, title="薄弱点强化包", description="纠错", resource_types=["讲义"],
        difficulty="中级", target_knowledge_point_ids=["node"],
    )
    plan = build_followup_plan(
        _profile(), selection, option, attempt_id="attempt", decision_id="decision", difficulty="中级",
        selection_type=None, correction_snapshot={"difficulty": "中级", "target_skill_nodes": ["node"]},
        historical_assessment_questions=[], intent_options=None, source_batch_id="  old-batch  ",
    )
    assert plan.source_batch_id == "old-batch"
    assert plan.resource_types == ["个性化纠错训练包", "分阶测试题"]
    assert plan.request.constraints["historical_assessment_questions_status"] == "unavailable"
    assert plan.request.constraints["selection_type"] == "correction_package"


def _attempt_inputs():
    questions = [ResourceEvaluationQuestion(
        question_id="q", question_type="short_answer", question="合成题干", skill_node_id="node",
    )]
    resource = LearningResource(
        resource_id="resource", learner_id="learner", resource_type="分阶测试题", topic="合成",
        difficulty="初级", content_text="合成资源", publication_status="published", learning_path_node="path",
        knowledge_points=["node"], source_refs=[],
    )
    payload = RunAttemptSubmitRequest(
        learner_id="learner", run_id="run", source_resource_id="resource", idempotency_key="evidence-fixture",
        expected_profile_version=1, submitted_at=datetime(2026, 10, 1, tzinfo=timezone.utc),
        answers=[{"question_id": "q", "answer": "合成作答"}], hint_count=7,
    )
    return questions, resource, payload


@pytest.mark.parametrize("scores,audit", [([0.79], "single_pass"), ([0.8, 0.85], "double_pass"), ([0.8, 0.95], "double_disagreement")])
def test_short_answer_recheck_does_not_replace_first_grade(scores, audit):
    questions, resource, payload = _attempt_inputs()
    calls = []
    pending = iter(scores)

    def grade(*args, **kwargs):
        calls.append(args)
        return next(pending)

    result = prepare_attempt_evidence(
        run_id="run", questions=questions, answer_key={"q": {"max_score": 10}}, payload=payload,
        selected_resource=resource, tutor_hint_count=3, tutor_hints_by_question={"q": 2}, score_answer=grade,
        tutor_batch_id="batch",
    )
    assert len(calls) == len(scores)
    assert result.knowledge_point_results[0].score == scores[0]
    assert result.metadata["scoring_audit"] == {"node": audit}
    assert result.metadata["total_score"] == round(scores[0] * 10, 1)
    assert result.metadata["question_trace"][0]["path_node_id"] == "path"
    assert result.metadata["assessment_session_id"] == "batch"
    assert result.hint_count == 3 and result.knowledge_point_results[0].hint_count == 2


def test_tutor_failure_falls_back_before_formal_commit(monkeypatch):
    questions, resource, payload = _attempt_inputs()

    class UnavailableTutor:
        def count_turns(self, *args, **kwargs):
            raise RuntimeError("synthetic unavailable telemetry")

    service = FeedbackService(MemoryFeedbackRepository(), tutor_repo=UnavailableTutor())
    monkeypatch.setattr(service, "_build_run_question_specs", lambda *args: (questions, {"q": {"max_score": 10}}))
    monkeypatch.setattr(service, "_answer_score", lambda *args, **kwargs: 0.5)
    commits = []
    monkeypatch.setattr(service, "process_learning_attempt", lambda *args, **kwargs: commits.append((args, kwargs)) or args[2])
    result = service.submit_run_attempt(_profile(), "run", [resource], payload, object(), tutor_batch_id="batch")
    assert len(commits) == 1
    assert result.hint_count == 7 and result.knowledge_point_results[0].hint_count == 0
    assert result.overall_score == 0.5
    assert commits[0][1] == {"verified_evidence": True, "require_session_trace": True, "schedule_followup": None}


def test_point_weights_and_question_order_survive_promotion_recheck():
    questions, resource, payload = _attempt_inputs()
    questions.append(ResourceEvaluationQuestion(question_id="objective", question_type="single_choice", question="合成选择题", skill_node_id="node"))
    wire = payload.model_dump()
    wire["answers"].append({"question_id": "objective", "answer": "A"})
    payload = RunAttemptSubmitRequest.model_validate(wire)
    calls = []

    def grade(question_type, expected, actual, **kwargs):
        calls.append(question_type)
        return 1.0 if question_type == "single_choice" else (0.8 if len(calls) == 1 else 0.5)

    result = prepare_attempt_evidence(
        run_id="run", questions=questions, answer_key={"q": {"max_score": 10}, "objective": {"max_score": 30}},
        payload=payload, selected_resource=resource, tutor_hint_count=4,
        tutor_hints_by_question={"q": 2, "objective": 1}, score_answer=grade,
    )
    assert calls == ["short_answer", "single_choice", "short_answer"]
    assert [item["question_id"] for item in result.metadata["question_results"]] == ["q", "objective"]
    assert result.metadata["total_score"] == 38.0 and result.metadata["max_score"] == 40.0
    assert result.knowledge_point_results[0].score == 0.95
    assert result.knowledge_point_results[0].hint_count == 3
    assert result.metadata["scoring_audit"] == {"node": "double_disagreement"}
