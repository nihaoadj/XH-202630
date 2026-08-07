"""聚合学习历史并输出给前端时间线。"""
from __future__ import annotations

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.feedback.base import BaseFeedbackRepository
from app.db.generation_job.base import BaseGenerationJobRepository
from app.db.questionnaire.base import BaseQuestionnaireRepository
from app.models.history_schemas import LearningHistoryEvent, LearningHistoryTimelineResponse
from app.services.profile_service import ProfileService


def _event_sort_value(event: LearningHistoryEvent) -> float:
    if event.occurred_at is None:
        return 0.0
    return event.occurred_at.timestamp()


class LearningHistoryService:
    def __init__(
        self,
        profile_service: ProfileService,
        questionnaire_repo: BaseQuestionnaireRepository,
        diagnosis_repo: BaseDiagnosisRepository,
        generation_job_repo: BaseGenerationJobRepository,
        feedback_repo: BaseFeedbackRepository,
    ):
        self.profile_service = profile_service
        self.questionnaire_repo = questionnaire_repo
        self.diagnosis_repo = diagnosis_repo
        self.generation_job_repo = generation_job_repo
        self.feedback_repo = feedback_repo

    def timeline(self, learner_id: str) -> LearningHistoryTimelineResponse | None:
        profile = self.profile_service.get(learner_id)
        if profile is None:
            return None

        events: list[LearningHistoryEvent] = []
        for submission in self.questionnaire_repo.list_submissions_by_learner(learner_id):
            title = "完成问卷"
            if submission.get("metadata", {}).get("purpose") == "initial_profile":
                title = "创建学习方向画像"
            events.append(
                LearningHistoryEvent(
                    event_id=submission["submission_id"],
                    event_type="questionnaire_submitted",
                    title=title,
                    description=f"学习方向 {submission.get('knowledge_base_id') or '-'} 的问卷已提交。",
                    occurred_at=submission.get("created_at"),
                    payload={
                        "questionnaire_id": submission["questionnaire_id"],
                        "knowledge_base_id": submission.get("knowledge_base_id"),
                        "answers": submission.get("answers", {}),
                    },
                )
            )

        for run in self.diagnosis_repo.list_runs_by_learner(learner_id):
            events.append(
                LearningHistoryEvent(
                    event_id=run.diagnostic_result_id,
                    event_type="diagnosis_completed",
                    title="完成能力诊断",
                    description=f"诊断结果为 {run.ability_level}，可据此选择资源类型。",
                    occurred_at=run.created_at,
                    status=run.ability_level,
                    payload=run.model_dump(mode="json"),
                )
            )

        feedback_by_id = {
            feedback.feedback_id: feedback
            for feedback in self.feedback_repo.list_by_learner(learner_id)
        }

        for job in self.generation_job_repo.list_by_learner(learner_id):
            request_payload = job.request_payload or {}
            constraints = request_payload.get("constraints") or {}
            based_on_feedback_id = constraints.get("based_on_feedback_id") or ""
            title = "发起资源生成"
            if job.job_status == "completed":
                title = "资源生成完成"
            elif job.job_status == "failed":
                title = "资源生成失败"
            if based_on_feedback_id:
                title = "基于反馈重新生成" if job.job_status == "completed" else "发起反馈后重新生成"
            linked_feedback = feedback_by_id.get(based_on_feedback_id)
            description = f"主题: {job.topic}"
            if linked_feedback:
                description = (
                    f"基于学习后测评 {linked_feedback.correct_rate:.0%} 和反馈决策"
                    f"「{linked_feedback.decision}」重新生成；主题: {job.topic}"
                )
            events.append(
                LearningHistoryEvent(
                    event_id=job.run_id,
                    event_type=f"generation_{job.job_status}",
                    title=title,
                    description=description,
                    occurred_at=job.finished_at or job.started_at or job.created_at,
                    status=job.job_status,
                    payload={
                        "run_id": job.run_id,
                        "knowledge_base_id": job.knowledge_base_id,
                        "resource_ids": job.resource_ids,
                        "error_message": job.error_message,
                        "topic": job.topic,
                        "based_on_feedback_id": based_on_feedback_id or None,
                        "based_on_feedback_run_id": constraints.get("based_on_feedback_run_id"),
                        "based_on_feedback_resource_ids": constraints.get("based_on_feedback_resource_ids", []),
                    },
                )
            )

        for feedback in feedback_by_id.values():
            practice_result = feedback.practice_result or {}
            event_type = (
                "post_learning_diagnosis_completed"
                if feedback.feedback_type in {"run_evaluation_feedback", "evaluation_feedback"}
                else "feedback_submitted"
            )
            title = "完成学习后测评/反馈诊断" if event_type == "post_learning_diagnosis_completed" else "提交学习反馈"
            correct = practice_result.get("evaluation_correct")
            total = practice_result.get("evaluation_total")
            score_text = f"{feedback.correct_rate:.0%}"
            if isinstance(correct, int) and isinstance(total, int) and total:
                score_text = f"{correct}/{total}，正确率 {feedback.correct_rate:.0%}"
            events.append(
                LearningHistoryEvent(
                    event_id=feedback.feedback_id,
                    event_type=event_type,
                    title=title,
                    description=(
                        f"测评结果 {score_text}；反馈 Agent 决策：{feedback.decision}；"
                        f"下一步：{feedback.next_action or '-'}。"
                    ),
                    occurred_at=feedback.created_at,
                    status=feedback.decision,
                    payload={
                        "feedback_id": feedback.feedback_id,
                        "resource_id": feedback.resource_id,
                        "run_id": practice_result.get("run_id"),
                        "correct_rate": feedback.correct_rate,
                        "feedback_type": feedback.feedback_type,
                        "decision": feedback.decision,
                        "decision_reason": feedback.decision_reason,
                        "next_action": feedback.next_action,
                        "recommended_topics": feedback.recommended_topics,
                        "wrong_knowledge_points": [
                            answer.knowledge_point
                            for answer in feedback.answers
                            if not answer.correct and answer.knowledge_point
                        ],
                        "updated_knowledge_states": {
                            key: value.model_dump(mode="json")
                            for key, value in feedback.updated_knowledge_states.items()
                        },
                        "regenerate_suggestion": feedback.regenerate_suggestion,
                        "practice_result": practice_result,
                    },
                )
            )

        events.sort(key=_event_sort_value, reverse=True)
        return LearningHistoryTimelineResponse(
            learner_id=learner_id,
            profile=profile,
            events=events,
        )
