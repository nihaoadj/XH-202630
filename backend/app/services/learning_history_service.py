"""聚合学习历史并输出给前端时间线。"""
from __future__ import annotations

from datetime import datetime

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.generation_job.base import BaseGenerationJobRepository
from app.db.questionnaire.base import BaseQuestionnaireRepository
from app.models.history_schemas import LearningHistoryEvent, LearningHistoryTimelineResponse
from app.services.profile_service import ProfileService


class LearningHistoryService:
    def __init__(
        self,
        profile_service: ProfileService,
        questionnaire_repo: BaseQuestionnaireRepository,
        diagnosis_repo: BaseDiagnosisRepository,
        generation_job_repo: BaseGenerationJobRepository,
    ):
        self.profile_service = profile_service
        self.questionnaire_repo = questionnaire_repo
        self.diagnosis_repo = diagnosis_repo
        self.generation_job_repo = generation_job_repo

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

        for job in self.generation_job_repo.list_by_learner(learner_id):
            title = "发起资源生成"
            if job.job_status == "completed":
                title = "资源生成完成"
            elif job.job_status == "failed":
                title = "资源生成失败"
            events.append(
                LearningHistoryEvent(
                    event_id=job.run_id,
                    event_type=f"generation_{job.job_status}",
                    title=title,
                    description=f"主题: {job.topic}",
                    occurred_at=job.finished_at or job.started_at or job.created_at,
                    status=job.job_status,
                    payload={
                        "run_id": job.run_id,
                        "knowledge_base_id": job.knowledge_base_id,
                        "resource_ids": job.resource_ids,
                        "error_message": job.error_message,
                        "topic": job.topic,
                    },
                )
            )

        events.sort(key=lambda item: item.occurred_at or datetime.min, reverse=True)
        return LearningHistoryTimelineResponse(
            learner_id=learner_id,
            profile=profile,
            events=events,
        )
