"""聚合学习历史并输出给前端时间线。"""
from __future__ import annotations

from collections import defaultdict

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.feedback.base import BaseFeedbackRepository
from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.db.generation.base import BaseGenerationJobRepository
from app.db.questionnaire.base import BaseQuestionnaireRepository
from app.db.learning_documents.base import BaseResourceRepository
from app.db.audit.base import BaseAuditRepository
from app.models.learners.history import (
    LearningHistoryEvent,
    LearningHistoryTimelineResponse,
    LearningJourneyCurrentState,
    LearningJourneyResponse,
    LearningJourneyRound,
)
from app.services.learners.profiles import ProfileService
from app.services.knowledge.knowledge import KnowledgeService


def _event_sort_value(event: LearningHistoryEvent) -> float:
    if event.occurred_at is None:
        return 0.0
    return event.occurred_at.timestamp()


def _datetime_sort_value(value) -> float:
    if value is None:
        return float("-inf")
    return value.timestamp()


class LearningHistoryService:
    def __init__(
        self,
        profile_service: ProfileService,
        questionnaire_repo: BaseQuestionnaireRepository,
        diagnosis_repo: BaseDiagnosisRepository,
        generation_job_repo: BaseGenerationJobRepository,
        feedback_repo: BaseFeedbackRepository,
        feedback_loop_repo: BaseFeedbackLoopRepository | None = None,
        resource_repo: BaseResourceRepository | None = None,
        audit_repo: BaseAuditRepository | None = None,
        knowledge_service: KnowledgeService | None = None,
    ):
        self.profile_service = profile_service
        self.questionnaire_repo = questionnaire_repo
        self.diagnosis_repo = diagnosis_repo
        self.generation_job_repo = generation_job_repo
        self.feedback_repo = feedback_repo
        self.feedback_loop_repo = feedback_loop_repo
        self.resource_repo = resource_repo
        self.audit_repo = audit_repo
        self.knowledge_service = knowledge_service

    def _job_topic(
        self,
        job,
        resources: list | None = None,
        resource_types: list[str] | None = None,
    ) -> str:
        """Display the frozen learning nodes together with this batch's types."""
        payload = job.request_payload if isinstance(job.request_payload, dict) else {}
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
        snapshot = constraints.get("learner_focus_snapshot") if isinstance(constraints.get("learner_focus_snapshot"), dict) else {}
        node_ids = payload.get("target_skill_nodes") or constraints.get("target_skill_node_ids") or snapshot.get("adopted_node_ids") or []
        node_ids = [str(item) for item in node_ids if item]
        names_by_id = {}
        if self.knowledge_service and job.knowledge_base_id:
            try:
                names_by_id = {
                    str(node.node_id): node.name
                    for node in self.knowledge_service.list_skill_nodes(job.knowledge_base_id)
                }
            except Exception:
                names_by_id = {}
        node_names = list(dict.fromkeys(names_by_id.get(item, item) for item in node_ids))
        if not node_names and resources:
            node_names = list(dict.fromkeys(
                str(point) for resource in resources for point in (resource.knowledge_points or []) if point
            ))
        requested_types = resource_types if resource_types is not None else payload.get("resource_types")
        if not isinstance(requested_types, list) and resources:
            requested_types = [resource.resource_type for resource in resources if resource.resource_type]
        requested_types = list(dict.fromkeys(str(item) for item in (requested_types or []) if item))
        if node_names and requested_types:
            return f"{'、'.join(node_names)}（{'、'.join(requested_types)}）"
        if node_names:
            return "、".join(node_names)
        return job.topic

    @staticmethod
    def _job_batch_id(job) -> str:
        return str(job.batch_id or job.run_id)

    @classmethod
    def _journey_round_id(cls, job) -> str:
        """Return the learner-round key, separating correction assessments.

        Correction resources intentionally retain the source batch_id so they
        remain discoverable with the original materials.  They nevertheless
        have a new assessment and must not inherit the source round's
        feedback/path projection.
        """
        batch_id = cls._job_batch_id(job)
        payload = job.request_payload if isinstance(job.request_payload, dict) else {}
        constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
        correction_snapshot = constraints.get("correction_focus_snapshot")
        is_correction = (
            isinstance(correction_snapshot, dict)
            or constraints.get("selection_type") == "correction_package"
            or "个性化纠错训练包" in (payload.get("resource_types") or [])
        )
        if not is_correction:
            return batch_id
        attempt_id = (
            constraints.get("feedback_attempt_id")
            or constraints.get("source_attempt_id")
            or (correction_snapshot or {}).get("source_attempt_id")
            or (correction_snapshot or {}).get("source_run_id")
            or job.run_id
        )
        return f"correction:{batch_id}:{attempt_id}"

    def journey(self, learner_id: str, *, offset: int = 0, limit: int = 20) -> LearningJourneyResponse | None:
        """Build a learner-readable chain from durable facts without inventing links.

        A batch can contain several auditable Runs (continuations, targeted
        retries, or feedback-generated additions).  They are one learner
        round, so feedback and path mutation must be projected onto the batch
        rather than onto whichever Run happened to own the assessment.
        """
        profile = self.profile_service.get(learner_id)
        if profile is None:
            return None

        jobs = self.generation_job_repo.list_by_learner(learner_id)
        results = self.feedback_loop_repo.list_results(learner_id, limit=500) if self.feedback_loop_repo else []
        jobs_by_run = {item.run_id: item for item in jobs}
        results_by_run = {
            item.attempt.source_run_id: item
            for item in results
            if item.attempt.source_run_id
        }
        results_by_round: dict[str, list] = defaultdict(list)
        for item in results:
            source_run_id = item.attempt.source_run_id
            metadata = item.attempt.metadata or {}
            batch_id = str(metadata.get("source_batch_id") or "").strip()
            source_job = jobs_by_run.get(source_run_id) if source_run_id else None
            if source_job is not None:
                round_id = self._journey_round_id(source_job)
            else:
                round_id = batch_id
            if not round_id and source_run_id:
                batch_id = str((source_job.batch_id if source_job else None) or source_run_id)
                round_id = batch_id
            if round_id:
                results_by_round[round_id].append(item)
        legacy_feedback_by_run = {
            str(item.practice_result.get("run_id")): item
            for item in self.feedback_repo.list_by_learner(learner_id)
            if item.practice_result.get("run_id")
        }
        relations_by_child = {
            relation.get("child_run_id"): relation
            for item in results for relation in item.followup_relations
            if relation.get("child_run_id")
        }
        relations_by_parent: dict[str, list[dict]] = defaultdict(list)
        for relation in relations_by_child.values():
            parent_run_id = relation.get("parent_run_id")
            if parent_run_id:
                relations_by_parent[str(parent_run_id)].append(relation)

        jobs_by_round: dict[str, list] = {}
        for job in jobs:
            round_id = self._journey_round_id(job)
            jobs_by_round.setdefault(round_id, []).append(job)

        rounds: list[LearningJourneyRound] = []
        for round_id, batch_jobs in jobs_by_round.items():
            # Repositories return newest jobs first.  The newest Run is the
            # useful progress/audit target, while the whole batch supplies the
            # learner-facing resources and resource-type label.
            batch_jobs = sorted(
                batch_jobs,
                key=lambda item: _datetime_sort_value(item.created_at),
            )
            representative_job = batch_jobs[-1]
            batch_id = self._job_batch_id(representative_job)
            run_ids = [item.run_id for item in batch_jobs]
            isolated_run_ids = {
                item.run_id
                for item in jobs
                if self._job_batch_id(item) == batch_id
                and self._journey_round_id(item) != batch_id
            }
            resources = self._batch_resources(
                learner_id,
                batch_id,
                run_ids,
                run_only=round_id != batch_id,
                exclude_run_ids=isolated_run_ids if round_id == batch_id else set(),
            )
            batch_results = sorted(
                results_by_round.get(round_id, []),
                key=lambda item: _datetime_sort_value(item.attempt.submitted_at),
            )
            result = batch_results[-1] if batch_results else None
            if result is None:
                result = next(
                    (results_by_run.get(run_id) for run_id in reversed(run_ids)
                     if results_by_run.get(run_id)),
                    None,
                )
            legacy_feedback = next(
                (legacy_feedback_by_run.get(run_id) for run_id in reversed(run_ids)
                 if legacy_feedback_by_run.get(run_id)),
                None,
            ) if result is None else None
            relations = [relations_by_child[run_id] for run_id in run_ids if run_id in relations_by_child]
            runs = [self.audit_repo.get_run(run_id) for run_id in run_ids if self.audit_repo]
            reviews = [
                review
                for run_id in run_ids
                if self.audit_repo
                for review in self.audit_repo.list_reviews_by_run(run_id)
            ]
            rounds.append(LearningJourneyRound(
                run_id=representative_job.run_id,
                batch_id=batch_id,
                run_ids=run_ids,
                round_id=round_id,
                topic=self._job_topic(
                    representative_job,
                    resources,
                    resource_types=[
                        resource_type
                        for job in batch_jobs
                        for resource_type in (job.request_payload or {}).get("resource_types", [])
                    ],
                ),
                status=self._batch_status(batch_jobs),
                occurred_at=min(
                    (item.finished_at or item.started_at or item.created_at for item in batch_jobs),
                    key=_datetime_sort_value,
                    default=None,
                ),
                is_followup=bool(relations) and len(relations) == len(run_ids),
                parent_run_id=(relations[0].get("parent_run_id") if len(relations) == 1 else None),
                resources=[self._resource_summary(item) for item in resources],
                assessment=(self._assessment_summary(result) if result else self._legacy_assessment_summary(legacy_feedback)),
                feedback=(self._feedback_summary(result) if result else self._legacy_feedback_summary(legacy_feedback)),
                path_change=(
                    self._path_change_summary(result, representative_job.knowledge_base_id)
                    if result else None
                ),
                run_summary=self._batch_run_summary(runs, reviews, batch_jobs),
            ))

        rounds_by_run = {
            run_id: round_item
            for round_item in rounds
            for run_id in round_item.run_ids
        }
        for round_item in rounds:
            if not round_item.path_change:
                continue
            next_rounds = []
            seen_next_runs: set[str] = set()
            for run_id in round_item.run_ids:
                for relation in relations_by_parent.get(run_id, []):
                    child_run_id = str(relation.get("child_run_id") or "")
                    child_round = rounds_by_run.get(child_run_id)
                    if (
                        child_round is None
                        or child_round.round_id == round_item.round_id
                        or child_round.run_id in seen_next_runs
                    ):
                        continue
                    seen_next_runs.add(child_round.run_id)
                    next_rounds.append({
                        "run_id": child_round.run_id,
                        "round_id": child_round.round_id,
                        "topic": child_round.topic,
                        "relation_type": relation.get("relation_type"),
                    })
            if next_rounds:
                round_item.path_change["next_steps"] = next_rounds

        page = rounds[offset:offset + limit]
        current_state = self._current_state(profile, results)
        linked_run_ids = {job.run_id for job in jobs}
        timeline = self.timeline(learner_id)
        unlinked_events = [
            event for event in (timeline.events if timeline else [])
            if event.payload.get("run_id") not in linked_run_ids
            and event.event_id not in linked_run_ids
        ]
        return LearningJourneyResponse(
            learner_id=learner_id,
            profile=profile,
            current_state=current_state,
            rounds=page,
            unlinked_events=unlinked_events,
            total_rounds=len(rounds),
            next_offset=offset + limit if offset + limit < len(rounds) else None,
        )

    def _batch_resources(
        self,
        learner_id: str,
        batch_id: str,
        run_ids: list[str],
        *,
        run_only: bool = False,
        exclude_run_ids: set[str] | None = None,
    ) -> list:
        """Return the batch's published resources, with a legacy Run fallback."""
        if self.resource_repo is None:
            return []
        if not run_only:
            resources = self.resource_repo.list_by_learner_with_filter(
                learner_id,
                batch_id=batch_id,
            )
            if exclude_run_ids:
                resources = [item for item in resources if item.run_id not in exclude_run_ids]
            if resources:
                return sorted(resources, key=lambda item: (item.resource_type, item.version, item.resource_id))

        # Old rows may have no batch_id even though their GenerationJob does.
        # Keep those records visible only when their Run belongs to this batch.
        by_id = {}
        for run_id in run_ids:
            for resource in self.resource_repo.list_by_run(run_id):
                if resource.learner_id == learner_id and resource.publication_status == "published":
                    by_id[resource.resource_id] = resource
        return sorted(by_id.values(), key=lambda item: (item.resource_type, item.version, item.resource_id))

    @staticmethod
    def _batch_status(jobs: list) -> str:
        statuses = {job.job_status for job in jobs}
        if "running" in statuses:
            return "running"
        if "queued" in statuses:
            return "queued"
        if "failed" in statuses:
            return "failed"
        return "completed"

    @staticmethod
    def _batch_run_summary(runs: list, reviews: list[dict], jobs: list) -> dict:
        available_runs = [run for run in runs if run is not None]
        errors = [job.error_message for job in jobs if job.error_message]
        if not available_runs:
            return {
                "availability": "legacy_or_unavailable",
                "run_count": len(jobs),
                "review_count": len(reviews),
                "error_message": errors[-1] if errors else None,
            }
        latest = available_runs[-1]
        return {
            "availability": "available",
            "run_count": len(jobs),
            "current_node": latest.current_node,
            "revision_count": max((run.revision_count or 0 for run in available_runs), default=0),
            "final_decision": latest.final_decision,
            "last_error_code": next((run.last_error_code for run in reversed(available_runs) if run.last_error_code), None),
            "review_count": len(reviews),
            "error_message": errors[-1] if errors else None,
        }

    @staticmethod
    def _resource_summary(resource) -> dict:
        return {
            "resource_id": resource.resource_id,
            "resource_type": resource.resource_type,
            "difficulty": resource.difficulty,
            "publication_status": resource.publication_status,
            "review_status": resource.review_status,
            "knowledge_points": resource.knowledge_points[:8],
            "version": resource.version,
            "published_at": resource.published_at,
        }

    @staticmethod
    def _assessment_summary(result) -> dict:
        attempt = result.attempt
        return {
            "attempt_id": attempt.attempt_id,
            "score": attempt.overall_score,
            "correct_count": sum(item.correct_count for item in attempt.knowledge_point_results),
            "total_count": sum(item.total_count for item in attempt.knowledge_point_results),
            "duration_ms": attempt.duration_ms,
            "hint_count": attempt.hint_count,
            "submitted_at": attempt.submitted_at,
            "knowledge_points": [
                {"knowledge_point_id": item.knowledge_point_id, "score": item.score,
                 "correct_count": item.correct_count, "total_count": item.total_count}
                for item in attempt.knowledge_point_results
            ],
        }

    @staticmethod
    def _feedback_summary(result) -> dict:
        decision = result.decision
        return {
            "action": decision.action.value,
            "reason": decision.decision_reason,
            "targets": decision.target_knowledge_point_ids,
            "next_action": (result.analysis.learner_suggestions[0] if result.analysis and result.analysis.learner_suggestions else None),
            "followup_run_ids": result.followup_run_ids,
        }

    @staticmethod
    def _legacy_assessment_summary(feedback) -> dict | None:
        if feedback is None:
            return None
        practice = feedback.practice_result or {}
        correct = practice.get("evaluation_correct")
        total = practice.get("evaluation_total")
        return {
            "attempt_id": feedback.feedback_id,
            "score": feedback.correct_rate,
            "correct_count": correct if isinstance(correct, int) else None,
            "total_count": total if isinstance(total, int) else None,
            "duration_ms": 0,
            "hint_count": 0,
            "submitted_at": feedback.created_at,
            "knowledge_points": [],
        }

    @staticmethod
    def _legacy_feedback_summary(feedback) -> dict | None:
        if feedback is None:
            return None
        return {
            "action": feedback.decision,
            "reason": feedback.decision_reason,
            "targets": list(dict.fromkeys(answer.knowledge_point for answer in feedback.answers
                                             if not answer.correct and answer.knowledge_point)),
            "next_action": feedback.next_action,
            "followup_run_ids": [],
        }

    def _path_change_summary(self, result, knowledge_base_id: str | None = None) -> dict:
        mutation = result.path_mutation
        path = getattr(result, "learning_path", None)
        path_nodes = {
            str(node.node_id): node
            for node in (getattr(path, "nodes", None) or [])
            if getattr(node, "node_id", None)
        }
        names_by_id = {}
        if self.knowledge_service and knowledge_base_id:
            try:
                names_by_id = {
                    str(node.node_id): node.name
                    for node in self.knowledge_service.list_skill_nodes(knowledge_base_id)
                }
            except Exception:
                names_by_id = {}

        def node_details(node_ids: list[str]) -> list[dict]:
            details = []
            for raw_node_id in node_ids:
                node_id = str(raw_node_id)
                node = path_nodes.get(node_id)
                knowledge_point_id = str(
                    getattr(node, "knowledge_point_id", None) or node_id
                )
                details.append({
                    "node_id": node_id,
                    "knowledge_point_id": knowledge_point_id,
                    "name": names_by_id.get(knowledge_point_id, knowledge_point_id),
                    "node_type": getattr(getattr(node, "node_type", None), "value", getattr(node, "node_type", None)),
                    "status": getattr(getattr(node, "status", None), "value", getattr(node, "status", None)),
                })
            return details

        assessed_nodes = []
        seen_assessed_ids: set[str] = set()
        attempt = getattr(result, "attempt", None)
        for item in getattr(attempt, "knowledge_point_results", []):
            knowledge_point_id = str(getattr(item, "knowledge_point_id", "") or "")
            if not knowledge_point_id or knowledge_point_id in seen_assessed_ids:
                continue
            seen_assessed_ids.add(knowledge_point_id)
            assessed_nodes.append({
                "node_id": knowledge_point_id,
                "knowledge_point_id": knowledge_point_id,
                "name": names_by_id.get(knowledge_point_id, knowledge_point_id),
            })

        return {
            "mutation_type": mutation.mutation_type.value,
            "completed_node_ids": mutation.completed_node_ids,
            "unlocked_node_ids": mutation.unlocked_node_ids,
            "inserted_node_ids": mutation.inserted_node_ids,
            "completed_nodes": node_details(mutation.completed_node_ids),
            "unlocked_nodes": node_details(mutation.unlocked_node_ids),
            "inserted_nodes": node_details(mutation.inserted_node_ids),
            "assessed_nodes": assessed_nodes,
            "path_version_before": mutation.path_version_before,
            "path_version_after": mutation.path_version_after,
            "mastery_changes": [
                {"knowledge_point_id": item.knowledge_point_id,
                 "before": item.before.mastery if item.before else None,
                 "after": item.after.mastery, "status": item.after.status}
                for item in result.knowledge_state_updates
            ],
        }

    @staticmethod
    def _run_summary(run, reviews: list[dict], job_error: str | None) -> dict:
        if run is None:
            return {"availability": "legacy_or_unavailable", "review_count": len(reviews), "error_message": job_error}
        return {
            "availability": "available",
            "status": run.status.value if hasattr(run.status, "value") else run.status,
            "current_node": run.current_node,
            "revision_count": run.revision_count,
            "final_decision": run.final_decision,
            "last_error_code": run.last_error_code,
            "review_count": len(reviews),
            "error_message": job_error,
        }

    def _current_state(self, profile, results) -> LearningJourneyCurrentState:
        path = self.feedback_loop_repo.get_current_path(profile.learner_id) if self.feedback_loop_repo else None
        nodes = path.nodes if path else []
        node_summary = lambda node: {"node_id": node.node_id, "knowledge_point_id": node.knowledge_point_id,
                                     "status": node.status.value, "difficulty": node.difficulty, "sequence": node.sequence}
        latest = max(results, key=lambda item: item.attempt.submitted_at, default=None)
        latest_assessment = self._assessment_summary(latest) if latest else None
        next_action = self._feedback_summary(latest).get("next_action") if latest else None
        return LearningJourneyCurrentState(
            path_id=path.path_id if path else None,
            path_version=path.version if path else None,
            current_nodes=[node_summary(item) for item in nodes if item.status.value == "in_progress"],
            completed_nodes=[node_summary(item) for item in nodes if item.status.value == "completed"],
            upcoming_nodes=[node_summary(item) for item in nodes if item.status.value in {"available", "locked"}],
            mastery=[{"knowledge_point_id": key, "score": value.score, "status": value.status}
                      for key, value in profile.knowledge_states.items()],
            next_action=next_action,
            latest_assessment=latest_assessment,
        )

    def timeline(self, learner_id: str) -> LearningHistoryTimelineResponse | None:
        profile = self.profile_service.get(learner_id)
        if profile is None:
            return None

        events: list[LearningHistoryEvent] = []
        submissions = self.questionnaire_repo.list_submissions_by_learner(learner_id)
        initial_profile_submissions: list[dict] = []
        for submission in submissions:
            if submission.get("metadata", {}).get("purpose") == "initial_profile":
                initial_profile_submissions.append(submission)
                continue
            title = "完成问卷"
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
        events.extend(self._build_initial_profile_events(initial_profile_submissions))

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
            supplemental_requirements = str(constraints.get("supplemental_requirements") or "").strip()
            based_on_feedback_id = constraints.get("based_on_feedback_id") or ""
            title = "发起资源生成"
            if job.job_status == "completed":
                title = "资源生成完成"
            elif job.job_status == "failed":
                title = "资源生成失败"
            if based_on_feedback_id:
                title = "基于反馈重新生成" if job.job_status == "completed" else "发起反馈后重新生成"
            linked_feedback = feedback_by_id.get(based_on_feedback_id)
            display_topic = self._job_topic(job)
            description = f"任务摘要：{display_topic}"
            if supplemental_requirements:
                description = f"{description}；补充要求：{supplemental_requirements}"
            if linked_feedback:
                description = (
                    f"基于学习后测评 {linked_feedback.correct_rate:.0%} 和反馈决策"
                    f"「{linked_feedback.decision}」重新生成；任务摘要：{job.topic}"
                )
                if supplemental_requirements:
                    description = f"{description}；补充要求：{supplemental_requirements}"
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
                        "supplemental_requirements": supplemental_requirements or None,
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

    def _build_initial_profile_events(self, submissions: list[dict]) -> list[LearningHistoryEvent]:
        grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for submission in submissions:
            key = (
                submission.get("learner_id") or "",
                self._created_at_key(submission.get("created_at")),
            )
            grouped[key].append(submission)

        events: list[LearningHistoryEvent] = []
        for grouped_submissions in grouped.values():
            ordered = sorted(
                grouped_submissions,
                key=lambda item: (
                    item.get("created_at").timestamp() if item.get("created_at") else 0.0,
                    item.get("submission_id") or "",
                ),
            )
            first = ordered[0]
            merged_answers: dict = {}
            questionnaire_ids: list[str] = []
            for submission in ordered:
                merged_answers.update(submission.get("answers", {}))
                questionnaire_id = submission.get("questionnaire_id")
                if questionnaire_id:
                    questionnaire_ids.append(questionnaire_id)
            events.append(
                LearningHistoryEvent(
                    event_id="__".join(item["submission_id"] for item in ordered),
                    event_type="initial_profile_created",
                    title="创建学习方向画像",
                    description=f"学习方向 {first.get('knowledge_base_id') or '-'} 的问卷已提交。",
                    occurred_at=first.get("created_at"),
                    payload={
                        "questionnaire_ids": questionnaire_ids,
                        "knowledge_base_id": first.get("knowledge_base_id"),
                        "answers": merged_answers,
                        "submission_count": len(ordered),
                    },
                )
            )
        return events

    @staticmethod
    def _created_at_key(value) -> str:
        if value is None:
            return "none"
        return value.isoformat()
