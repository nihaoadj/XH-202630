import json
import uuid

from app.agents.feedback import apply_feedback_decision, decide_feedback
from app.db.feedback.base import BaseFeedbackRepository
from app.models.schemas import (
    FeedbackAnswer,
    FeedbackRecord,
    FeedbackRequest,
    FeedbackResponse,
    LearnerProfile,
    LearningResource,
    ResourceEvaluationQuestion,
    ResourceEvaluationSessionResponse,
    ResourceEvaluationSubmitRequest,
    ResourceEvaluationSubmitResponse,
    RunEvaluationSessionResponse,
    RunEvaluationSubmitRequest,
    RunEvaluationSubmitResponse,
)
from app.services.knowledge_service import KnowledgeService


class FeedbackService:
    """Handle learning feedback and post-learning evaluations."""

    def __init__(self, feedback_repo: BaseFeedbackRepository):
        self.feedback_repo = feedback_repo

    def process_feedback(self, profile: LearnerProfile, req: FeedbackRequest) -> FeedbackResponse:
        history = self.feedback_repo.list_by_learner(req.learner_id)
        decision_result = decide_feedback(profile, req, history)
        apply_feedback_decision(profile, req, decision_result)

        record = FeedbackRecord(
            feedback_id=str(uuid.uuid4()),
            learner_id=req.learner_id,
            resource_id=req.resource_id,
            correct_rate=req.correct_rate,
            decision=decision_result.decision,
            answers=req.answers,
            feedback_type=req.feedback_type,
            time_spent_seconds=req.time_spent_seconds,
            completed=req.completed,
            self_rating=req.self_rating,
            practice_result=req.practice_result,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )
        self.feedback_repo.save(record)

        return FeedbackResponse(
            learner_id=req.learner_id,
            decision=decision_result.decision,
            message=f"根据正确率 {req.correct_rate:.0%}，系统决定：{decision_result.decision}",
            updated_profile=profile,
            decision_reason=decision_result.decision_reason,
            next_action=decision_result.next_action,
            recommended_topics=decision_result.recommended_topics,
            updated_knowledge_states=decision_result.updated_knowledge_states,
            regenerate_suggestion=decision_result.regenerate_suggestion,
        )

    def list_history(self, learner_id: str) -> list[FeedbackRecord]:
        return self.feedback_repo.list_by_learner(learner_id)

    def build_evaluation_session(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        knowledge_service: KnowledgeService,
    ) -> ResourceEvaluationSessionResponse:
        questions, _ = self._build_question_specs(profile, resource, knowledge_service)
        return ResourceEvaluationSessionResponse(
            learner_id=profile.learner_id,
            resource_id=resource.resource_id,
            topic=resource.topic,
            total=len(questions),
            questions=questions,
        )

    def build_run_evaluation_session(
        self,
        profile: LearnerProfile,
        run_id: str,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
    ) -> RunEvaluationSessionResponse:
        questions, _ = self._build_run_question_specs(profile, resources, knowledge_service)
        topic = self._merge_topics(resources)
        return RunEvaluationSessionResponse(
            learner_id=profile.learner_id,
            run_id=run_id,
            topic=topic,
            resource_ids=[resource.resource_id for resource in resources],
            total=len(questions),
            questions=questions,
        )

    def submit_evaluation_feedback(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        payload: ResourceEvaluationSubmitRequest,
        knowledge_service: KnowledgeService,
    ) -> ResourceEvaluationSubmitResponse:
        questions, answer_key = self._build_question_specs(profile, resource, knowledge_service)
        if not questions:
            raise ValueError("当前资源暂时没有可用测评题目")

        submitted_answers = {item.question_id: item.answer for item in payload.answers}
        feedback_answers: list[FeedbackAnswer] = []
        wrong_points: list[str] = []
        correct_count = 0

        for question in questions:
            actual_answer = submitted_answers.get(question.question_id)
            expected_answer = answer_key.get(question.question_id)
            is_correct = self._answers_match(expected_answer, actual_answer)
            if is_correct:
                correct_count += 1
            elif question.knowledge_point:
                wrong_points.append(question.knowledge_point)

            feedback_answers.append(
                FeedbackAnswer(
                    question_id=question.question_id,
                    correct=is_correct,
                    answer=actual_answer,
                    knowledge_point=question.knowledge_point,
                    difficulty=question.difficulty,
                    expected_answer=expected_answer,
                )
            )

        correct_rate = correct_count / len(questions)
        practice_result = dict(payload.practice_result or {})
        practice_result["evaluation_total"] = len(questions)
        practice_result["evaluation_correct"] = correct_count
        practice_result["resource_topic"] = resource.topic

        feedback_response = self.process_feedback(
            profile,
            FeedbackRequest(
                learner_id=payload.learner_id,
                resource_id=payload.resource_id,
                correct_rate=correct_rate,
                feedback_type=payload.feedback_type or "evaluation_feedback",
                time_spent_seconds=payload.time_spent_seconds,
                completed=payload.completed,
                self_rating=payload.self_rating,
                practice_result=practice_result,
                answers=feedback_answers,
            ),
        )

        return ResourceEvaluationSubmitResponse(
            learner_id=payload.learner_id,
            resource_id=payload.resource_id,
            correct_rate=correct_rate,
            correct_count=correct_count,
            total_questions=len(questions),
            wrong_knowledge_points=list(dict.fromkeys(point for point in wrong_points if point)),
            feedback=feedback_response,
        )

    def submit_run_evaluation_feedback(
        self,
        profile: LearnerProfile,
        run_id: str,
        resources: list[LearningResource],
        payload: RunEvaluationSubmitRequest,
        knowledge_service: KnowledgeService,
    ) -> RunEvaluationSubmitResponse:
        questions, answer_key = self._build_run_question_specs(profile, resources, knowledge_service)
        if not questions:
            raise ValueError("当前任务暂时没有可用测评题目")

        submitted_answers = {item.question_id: item.answer for item in payload.answers}
        feedback_answers: list[FeedbackAnswer] = []
        wrong_points: list[str] = []
        correct_count = 0

        for question in questions:
            actual_answer = submitted_answers.get(question.question_id)
            expected_answer = answer_key.get(question.question_id)
            is_correct = self._answers_match(expected_answer, actual_answer)
            if is_correct:
                correct_count += 1
            elif question.knowledge_point:
                wrong_points.append(question.knowledge_point)

            feedback_answers.append(
                FeedbackAnswer(
                    question_id=question.question_id,
                    correct=is_correct,
                    answer=actual_answer,
                    knowledge_point=question.knowledge_point,
                    difficulty=question.difficulty,
                    expected_answer=expected_answer,
                )
            )

        correct_rate = correct_count / len(questions)
        primary_resource = resources[0]
        practice_result = dict(payload.practice_result or {})
        practice_result["evaluation_total"] = len(questions)
        practice_result["evaluation_correct"] = correct_count
        practice_result["resource_topic"] = self._merge_topics(resources)
        practice_result["run_id"] = run_id
        practice_result["evaluated_resource_ids"] = [resource.resource_id for resource in resources]
        practice_result["evaluated_resource_count"] = len(resources)

        feedback_response = self.process_feedback(
            profile,
            FeedbackRequest(
                learner_id=payload.learner_id,
                resource_id=primary_resource.resource_id,
                correct_rate=correct_rate,
                feedback_type=payload.feedback_type or "run_evaluation_feedback",
                time_spent_seconds=payload.time_spent_seconds,
                completed=payload.completed,
                self_rating=payload.self_rating,
                practice_result=practice_result,
                answers=feedback_answers,
            ),
        )

        return RunEvaluationSubmitResponse(
            learner_id=payload.learner_id,
            run_id=run_id,
            resource_count=len(resources),
            correct_rate=correct_rate,
            correct_count=correct_count,
            total_questions=len(questions),
            wrong_knowledge_points=list(dict.fromkeys(point for point in wrong_points if point)),
            feedback=feedback_response,
        )

    def _build_question_specs(
        self,
        profile: LearnerProfile,
        resource: LearningResource,
        knowledge_service: KnowledgeService,
        limit: int = 10,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        questions: list[ResourceEvaluationQuestion] = []
        answer_key: dict[str, object] = {}

        for item in resource.exercise_items:
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type="short_answer",
                    question=item.question,
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    source="resource",
                )
            )
            answer_key[item.question_id] = item.answer

        if len(questions) >= limit:
            return questions[:limit], answer_key

        if not profile.knowledge_base_id:
            return questions[:limit], answer_key

        tokens = [resource.topic or "", *(resource.knowledge_points or [])]
        seen_question_ids = {question.question_id for question in questions}
        related = []
        for item in knowledge_service.load_diagnostic_questions(profile.knowledge_base_id):
            if item.question_id in seen_question_ids:
                continue
            searchable = " ".join(
                [
                    item.question or "",
                    item.knowledge_point or "",
                    " ".join(item.options or []),
                ]
            )
            if any(token and token in searchable for token in tokens):
                related.append(item)

        if not related:
            related = [
                item
                for item in knowledge_service.select_diagnostic_questions(
                    profile.knowledge_base_id,
                    limit=limit,
                )
                if item.question_id not in seen_question_ids
            ]

        for item in related[: max(0, limit - len(questions))]:
            questions.append(
                ResourceEvaluationQuestion(
                    question_id=item.question_id,
                    question_type=item.question_type,
                    question=item.question,
                    options=item.options or [],
                    knowledge_point=item.knowledge_point,
                    difficulty=item.difficulty,
                    source="knowledge_base",
                )
            )
            answer_key[item.question_id] = item.answer

        return questions, answer_key

    def _build_run_question_specs(
        self,
        profile: LearnerProfile,
        resources: list[LearningResource],
        knowledge_service: KnowledgeService,
        limit: int = 10,
    ) -> tuple[list[ResourceEvaluationQuestion], dict[str, object]]:
        merged_questions: list[ResourceEvaluationQuestion] = []
        merged_answer_key: dict[str, object] = {}
        seen_question_ids: set[str] = set()

        for resource in resources:
            questions, answer_key = self._build_question_specs(profile, resource, knowledge_service, limit=10)
            for question in questions:
                if question.question_id in seen_question_ids:
                    continue
                merged_questions.append(question)
                merged_answer_key[question.question_id] = answer_key.get(question.question_id)
                seen_question_ids.add(question.question_id)
                if len(merged_questions) >= limit:
                    return merged_questions, merged_answer_key

        return merged_questions, merged_answer_key

    @staticmethod
    def _merge_topics(resources: list[LearningResource]) -> str:
        topics = [resource.topic for resource in resources if resource.topic]
        unique_topics = list(dict.fromkeys(topics))
        return " / ".join(unique_topics[:3]) if unique_topics else ""

    @staticmethod
    def _answers_match(expected: object, actual: object) -> bool:
        return json.dumps(expected, ensure_ascii=False, sort_keys=True) == json.dumps(
            actual,
            ensure_ascii=False,
            sort_keys=True,
        )
