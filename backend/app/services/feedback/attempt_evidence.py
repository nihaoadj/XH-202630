"""Prepare scored evidence; storage, Tutor reads and formal commits stay in Service."""

from collections.abc import Callable

from app.models.feedback.feedback_loop import LearningAttemptSubmit
from app.models.learning_documents.schemas import (
    LearningResource, ResourceEvaluationQuestion, RunAttemptSubmitRequest,
)
from app.models.shared.persistence import canonical_hash
from app.services.feedback.assessment import _round_assessment_score


def question_result_key(question: ResourceEvaluationQuestion) -> str:
    return question.skill_node_id or question.knowledge_point or "综合能力"

def question_trace_item(question: ResourceEvaluationQuestion, fallback_path_node_id: str | None) -> dict[str, object]:
    return {
        "question_id": question.question_id,
        "question_type": question.question_type,
        "skill_node_id": question.skill_node_id,
        "path_node_id": question.path_node_id or fallback_path_node_id,
        "knowledge_point": question.knowledge_point,
        "difficulty": question.difficulty,
        "diagnostic_dimension": question.diagnostic_dimension,
        "source": question.source,
        "question_text": question.question,
    }

def prepare_attempt_evidence(
    *,
    run_id: str,
    questions: list[ResourceEvaluationQuestion],
    answer_key: dict[str, object],
    payload: RunAttemptSubmitRequest,
    selected_resource: LearningResource,
    tutor_hint_count: int,
    tutor_hints_by_question: dict[str, int],
    score_answer: Callable[..., float],
    tutor_batch_id: str | None = None,
) -> LearningAttemptSubmit:
    """Keep grading order, weights, promotion rechecks and trace payload unchanged."""
    submitted_answers = {item.question_id: item.answer for item in payload.answers}
    point_results: dict[str, dict[str, object]] = {}
    score_ratios_by_point: dict[str, list[float]] = {}
    score_totals_by_point: dict[str, float] = {}
    max_scores_by_point: dict[str, float] = {}
    short_answer_questions_by_point: dict[str, list[ResourceEvaluationQuestion]] = {}
    question_results: list[dict[str, object]] = []
    for question in questions:
        knowledge_point_id = question_result_key(question)
        result = point_results.setdefault(
            knowledge_point_id,
            {
                "question_ids": [],
                "correct_count": 0,
                "total_count": 0,
                "skill_node_ids": [],
                "knowledge_points": [],
                "diagnostic_dimensions": [],
            },
        )
        result["question_ids"].append(question.question_id)
        result["total_count"] += 1
        if question.skill_node_id and question.skill_node_id not in result["skill_node_ids"]:
            result["skill_node_ids"].append(question.skill_node_id)
        if question.knowledge_point and question.knowledge_point not in result["knowledge_points"]:
            result["knowledge_points"].append(question.knowledge_point)
        if question.diagnostic_dimension and question.diagnostic_dimension not in result["diagnostic_dimensions"]:
            result["diagnostic_dimensions"].append(question.diagnostic_dimension)
        score_ratio = score_answer(
            question.question_type,
            answer_key.get(question.question_id),
            submitted_answers.get(question.question_id),
            options=question.options,
        )
        score_ratios_by_point.setdefault(knowledge_point_id, []).append(score_ratio)
        if question.question_type == "short_answer":
            short_answer_questions_by_point.setdefault(knowledge_point_id, []).append(question)
        expected = answer_key.get(question.question_id)
        maximum = float(expected.get("max_score", 1.0)) if isinstance(expected, dict) else 1.0
        score_totals_by_point[knowledge_point_id] = (
            score_totals_by_point.get(knowledge_point_id, 0.0) + score_ratio * maximum
        )
        max_scores_by_point[knowledge_point_id] = (
            max_scores_by_point.get(knowledge_point_id, 0.0) + maximum
        )
        correct_threshold = 0.6 if question.question_type == "short_answer" else 1.0
        if score_ratio >= correct_threshold:
            result["correct_count"] += 1
        question_results.append({
            "question_id": question.question_id, "question_type": question.question_type,
            "skill_node_id": question.skill_node_id, "knowledge_point": question.knowledge_point,
            "correct": score_ratio >= correct_threshold,
            "score": _round_assessment_score(score_ratio * maximum),
            "max_score": _round_assessment_score(maximum),
            "grading_method": "llm" if question.question_type == "short_answer" else "deterministic",
        })

    # A short-answer grade can participate in mastery only when a possible
    # promotion is independently re-graded.  Ordinary practice feedback
    # remains single-pass and inexpensive.
    scoring_audit: dict[str, str] = {}
    for point_id, ratios in score_ratios_by_point.items():
        short_questions = short_answer_questions_by_point.get(point_id, [])
        if not short_questions or sum(ratios) / len(ratios) < 0.80:
            scoring_audit[point_id] = "single_pass"
            continue
        disagreements = False
        for question in short_questions:
            first_score = next(
                float(item["score"]) / float(item["max_score"])
                for item in question_results
                if item["question_id"] == question.question_id
            )
            second_score = score_answer(
                question.question_type,
                answer_key.get(question.question_id),
                submitted_answers.get(question.question_id),
                options=question.options,
            )
            if abs(first_score - second_score) > 0.10:
                disagreements = True
                break
        scoring_audit[point_id] = "double_disagreement" if disagreements else "double_pass"

    metadata = dict(payload.metadata)
    evaluation_sources = list(dict.fromkeys(question.source for question in questions))
    metadata.update(
        {
            "assessment_kind": "learning_check",
            "assessment_session_id": tutor_batch_id or run_id,
            "assessment_form_id": canonical_hash({
                "run_id": run_id,
                "question_ids": [question.question_id for question in questions],
            }),
            "scoring_audit": scoring_audit,
            "evaluation_source": evaluation_sources[0] if len(evaluation_sources) == 1 else "mixed",
            "question_count": len(questions),
            "question_trace": [
                question_trace_item(question, selected_resource.learning_path_node)
                for question in questions
            ],
            "point_trace": {
                knowledge_point_id: {
                    "skill_node_ids": values["skill_node_ids"],
                    "knowledge_points": values["knowledge_points"],
                    "diagnostic_dimensions": values["diagnostic_dimensions"],
                }
                for knowledge_point_id, values in point_results.items()
            },
            "question_results": question_results,
            "total_score": _round_assessment_score(sum(float(item["score"]) for item in question_results)),
            "max_score": _round_assessment_score(sum(float(item["max_score"]) for item in question_results)),
        }
    )

    return LearningAttemptSubmit(
        learner_id=payload.learner_id,
        source_resource_id=selected_resource.resource_id,
        source_resource_version=selected_resource.version,
        source_run_id=run_id,
        path_node_id=payload.path_node_id,
        idempotency_key=payload.idempotency_key,
        expected_profile_version=payload.expected_profile_version,
        started_at=payload.started_at,
        submitted_at=payload.submitted_at,
        duration_ms=payload.duration_ms,
        hint_count=tutor_hint_count,
        knowledge_point_results=[
            {
                "knowledge_point_id": knowledge_point_id,
                "question_ids": values["question_ids"],
                "correct_count": values["correct_count"],
                "total_count": values["total_count"],
                "score": score_totals_by_point[knowledge_point_id] / max_scores_by_point[knowledge_point_id],
                "hint_count": sum(
                    tutor_hints_by_question.get(question_id, 0)
                    for question_id in values["question_ids"]
                ),
            }
            for knowledge_point_id, values in point_results.items()
        ],
        metadata=metadata,
    )
