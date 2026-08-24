from app.db.feedback.base import BaseFeedbackRepository
from app.db.generation.base import BaseGenerationJobRepository
from app.db.learning_documents.base import BaseResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.services.learners.mastery import MasteryService
from datetime import datetime, timezone


class ReportService:
    """学情报告业务服务
    
    通过构造函数注入依赖。
    """

    def __init__(
        self,
        resource_repo: BaseResourceRepository,
        feedback_repo: BaseFeedbackRepository,
        feedback_loop_repo: BaseFeedbackLoopRepository | None = None,
        generation_job_repo: BaseGenerationJobRepository | None = None,
        mastery_service: MasteryService | None = None,
    ):
        self.resource_repo = resource_repo
        self.feedback_repo = feedback_repo
        self.feedback_loop_repo = feedback_loop_repo
        self.generation_job_repo = generation_job_repo
        self.mastery_service = mastery_service

    def build_report(self, profile: LearnerProfile) -> dict:
        """构建学情报告"""
        generated_at = datetime.now(timezone.utc)
        ability_projection = self.mastery_service.ability_nodes(profile) if self.mastery_service else None
        measured_nodes = [
            node for node in (ability_projection.nodes if ability_projection else [])
            if node.mastery.objective_evidence_count > 0 and node.mastery.mastery_score is not None
        ]
        topics = [node.name for node in measured_nodes] or list(profile.theory_scores.keys())
        scores = [round(float(node.mastery.mastery_score) * 100, 1) for node in measured_nodes] \
            or list(profile.theory_scores.values())
        resources = self._visible_resources(profile.learner_id)
        feedback = self.feedback_repo.list_by_learner(profile.learner_id)
        weak_points = ([node.name for node in measured_nodes if node.mastery.status.value == "weak"]
                       if ability_projection else list(dict.fromkeys(profile.weak_points)))
        strong_points = ([node.name for node in measured_nodes if node.mastery.status.value == "mastered"]
                         if ability_projection else list(dict.fromkeys(profile.strong_points)))
        avg_feedback = (
            sum(item.correct_rate for item in feedback) / len(feedback)
            if feedback
            else None
        )
        attempts = self.feedback_loop_repo.list_attempts(profile.learner_id, 10) if self.feedback_loop_repo else []
        loop_results = self.feedback_loop_repo.list_results(profile.learner_id, 10) if self.feedback_loop_repo else []
        formal_feedback = [
            {
                "feedback_id": item.attempt.attempt_id,
                "learner_id": item.attempt.learner_id,
                "resource_id": item.attempt.source_resource_id,
                "correct_rate": item.attempt.overall_score,
                "decision": item.decision.action.value,
                "decision_reason": item.decision.decision_reason,
                "next_action": item.decision.action.value,
                "recommended_topics": item.decision.target_knowledge_point_ids,
                "created_at": item.attempt.created_at,
            }
            for item in loop_results
        ]
        report_feedback = formal_feedback or feedback
        report_average = (
            sum(item["correct_rate"] for item in formal_feedback) / len(formal_feedback)
            if formal_feedback else avg_feedback
        )
        path = self.feedback_loop_repo.get_current_path(profile.learner_id) if self.feedback_loop_repo else None
        versions = self.feedback_loop_repo.list_profile_versions(profile.learner_id, 10) if self.feedback_loop_repo else []
        mastery_events = (
            self.mastery_service.repository.list_events(profile.learner_id, profile.knowledge_base_id)
            if self.mastery_service and profile.knowledge_base_id else []
        )
        priorities = ability_projection.weakness_priorities if ability_projection else []
        ability_names = {
            node.skill_node_id: node.name for node in (ability_projection.nodes if ability_projection else [])
        }

        return {
            "report_schema_version": "2.0",
            "as_of_profile_version": profile.profile_version,
            "generated_at": generated_at,
            "learner_id": profile.learner_id,
            "radar": {
                "dimensions": topics,
                "values": scores,
            },
            "weak_points": weak_points,
            "strong_points": strong_points,
            "skill_level": profile.skill_level,
            "learning_goal": profile.learning_goal,
            "difficulty_curve": ([
                {
                    "topic": node.name,
                    "score": round(float(node.mastery.mastery_score) * 100, 1),
                    "recommended_difficulty": "初级" if node.mastery.mastery_score < 0.60 else "中级" if node.mastery.mastery_score <= 0.85 else "高级",
                }
                for node in measured_nodes
            ] if ability_projection else [
                {"topic": t, "score": s, "recommended_difficulty": "初级" if s < 60 else "中级" if s < 80 else "高级"}
                for t, s in profile.theory_scores.items()
            ]),
            "learning_path": [
                {
                    "order": index + 1,
                    "topic": point,
                    "reason": "当前画像中的薄弱项，建议优先补齐",
                }
                for index, point in enumerate(weak_points[:5])
            ],
            "blind_spot_heatmap": [
                {
                    "topic": point,
                    "score": profile.theory_scores.get(point, 0),
                    "status": profile.knowledge_states.get(point).status
                    if point in profile.knowledge_states
                    else "weak",
                }
                for point in weak_points
            ],
            "agent_flow": [
                {
                    "agent_name": "feedback_decision",
                    "node_name": "feedback_decision",
                    "action": item.decision.action.value,
                    "output_summary": item.decision.decision_reason,
                    "run_id": item.attempt.source_run_id,
                    "status": "success",
                    "input_payload": {
                        "attempt_id": item.attempt.attempt_id,
                        "overall_score": item.attempt.overall_score,
                        "knowledge_point_count": len(item.attempt.knowledge_point_results),
                        "expected_profile_version": item.attempt.expected_profile_version,
                    },
                    "output_payload": {
                        "decision_id": item.decision.decision_id,
                        "reason_codes": item.decision.reason_codes,
                        "profile_version": item.profile_version,
                        "path_mutation_id": item.path_mutation.mutation_id,
                        "followup_generation_status": item.followup_generation_status.value,
                        "child_run_id": item.followup_run_id,
                    },
                    "decision_reason": item.decision.decision_reason,
                }
                for item in loop_results
            ],
            "resource_difficulty_match": [
                {
                    "resource_id": resource.resource_id,
                    "resource_type": resource.resource_type,
                    "difficulty": resource.difficulty,
                    "difficulty_match": resource.difficulty_match,
                    "review_status": resource.review_status,
                }
                for resource in resources[-10:]
            ],
            "review_summary": {
                "resource_count": len(resources),
                "passed_count": len([
                    resource
                    for resource in resources
                    if resource.review_status in {"passed", "approved"}
                ]),
                "average_hallucination_rate": self._average_hallucination_rate(resources),
            },
            "feedback_trend": [
                {
                    "resource_id": item["resource_id"] if isinstance(item, dict) else item.resource_id,
                    "correct_rate": item["correct_rate"] if isinstance(item, dict) else item.correct_rate,
                    "decision": item["decision"] if isinstance(item, dict) else item.decision,
                    "created_at": (
                        item.get("created_at").isoformat() if isinstance(item, dict) and item.get("created_at")
                        else item.created_at.isoformat() if not isinstance(item, dict) and item.created_at else None
                    ),
                }
                for item in report_feedback[:10]
            ],
            "metric_summary": {
                "resource_count": len(resources),
                "feedback_count": len(report_feedback),
                "average_correct_rate": report_average,
                "weak_point_count": len(weak_points),
            },
            "next_suggestions": (
                [ability_names.get(item.skill_node_id, item.skill_node_id) for item in priorities[:3]]
                if priorities else self._latest_feedback_suggestions(attempts, weak_points, profile)
            ),
            "recent_resources": resources[-5:],
            "recent_feedback": report_feedback[:5],
            "profile_version": profile.profile_version,
            "knowledge_mastery": ({
                node.skill_node_id: node.mastery.model_dump(mode="json")
                for node in ability_projection.nodes
            } if ability_projection else {
                key: value.model_dump(mode="json") for key, value in profile.knowledge_states.items()
            }),
            "current_learning_path": path.model_dump(mode="json") if path else None,
            "recent_attempts": [item.model_dump(mode="json") for item in attempts],
            "feedback_analysis": [
                {
                    "attempt_id": item.attempt_id,
                    **item.metadata["llm_analysis"],
                }
                for item in attempts
                if isinstance(item.metadata.get("llm_analysis"), dict)
            ],
            "recent_feedback_decisions": [
                item.decision.model_dump(mode="json") for item in loop_results
            ],
            "recent_knowledge_state_mutations": [
                {
                    "attempt_id": item.attempt.attempt_id,
                    **mutation.model_dump(mode="json"),
                }
                for item in loop_results
                for mutation in item.knowledge_state_updates
            ],
            "recent_followup_runs": [
                {
                    "attempt_id": item.attempt.attempt_id,
                    "decision_id": item.decision.decision_id,
                    "parent_run_id": item.attempt.source_run_id,
                    "child_run_id": item.followup_run_id,
                    "trigger_type": item.decision.action.value,
                    "status": item.followup_generation_status.value,
                    "error_code": item.followup_error_code,
                }
                for item in loop_results
                if item.followup_generation_status.value != "not_requested"
            ],
            "profile_versions": [item.model_dump(mode="json") for item in versions],
            "ability_nodes": ability_projection.nodes if ability_projection else [],
            "mastery_summary": ability_projection.summary.model_dump(mode="json") if ability_projection else {},
            "mastery_trend": [
                {
                    "event_id": event.evidence_id,
                    "skill_node_id": event.skill_node_id,
                    "source_type": event.source_type.value,
                    "verified": event.verified,
                    "observed_score": event.observed_score,
                    "mastery_score": event.after_state.mastery_score,
                    "occurred_at": event.occurred_at,
                }
                for event in mastery_events
            ],
            "evidence_coverage": ({
                "objective_node_count": ability_projection.summary.medium_or_high_confidence_count,
                "total_node_count": ability_projection.summary.total_count,
                "ratio": (
                    ability_projection.summary.medium_or_high_confidence_count
                    / ability_projection.summary.total_count
                    if ability_projection.summary.total_count else None
                ),
                "not_measured_count": (
                    ability_projection.summary.unassessed_count
                    + ability_projection.summary.self_reported_count
                ),
            } if ability_projection else {}),
            "weakness_priorities": priorities,
            "next_resource_focus": {
                "focus_mode": "auto",
                "adopted_node_ids": [item.skill_node_id for item in priorities[:3]],
                "reason_codes": {item.skill_node_id: item.reason_codes for item in priorities[:3]},
            },
            "data_warnings": ability_projection.data_warnings if ability_projection else ["MASTERY_PROJECTION_UNAVAILABLE"],
        }

    def _average_hallucination_rate(self, resources) -> float:
        values = [
            resource.hallucination_rate
            for resource in resources
            if resource.hallucination_rate is not None
        ]
        if not values:
            return 0.0
        return sum(values) / len(values)

    def _visible_resources(self, learner_id: str):
        """Return the learner-facing projection, excluding superseded versions."""
        resources = self.resource_repo.list_by_learner(learner_id)
        if self.generation_job_repo is None:
            return resources

        jobs = self.generation_job_repo.list_by_learner(learner_id)
        superseded_run_ids = {
            job.run_id for job in jobs if job.superseded_by_run_id
        }
        published_types_by_run: dict[str, set[str]] = {}
        for resource in resources:
            published_types_by_run.setdefault(resource.run_id or "", set()).add(
                resource.resource_type
            )
        latest_replacement_by_type = {}
        for job in jobs:
            if job.superseded_by_run_id:
                continue
            types = (job.request_payload.get("constraints") or {}).get(
                "replacement_resource_types", [],
            )
            batch_id = job.batch_id or job.run_id
            for resource_type in types:
                # Replacement metadata is declarative. It becomes effective
                # only when this Run actually published that resource type;
                # an appended checklist or failed retry must never hide an
                # earlier published assessment or lecture.
                if resource_type not in published_types_by_run.get(job.run_id, set()):
                    continue
                key = (batch_id, resource_type)
                current = latest_replacement_by_type.get(key)
                if current is None or str(job.created_at or "") > str(current.created_at or ""):
                    latest_replacement_by_type[key] = job

        return [
            resource
            for resource in resources
            if resource.run_id not in superseded_run_ids
            and (
                (replacement := latest_replacement_by_type.get(
                    (resource.batch_id or resource.run_id, resource.resource_type),
                )) is None
                or resource.run_id == replacement.run_id
            )
        ]

    @staticmethod
    def _latest_feedback_suggestions(attempts, weak_points, profile) -> list[str]:
        """Prefer bounded learner-facing analysis, while retaining a deterministic fallback."""
        for attempt in attempts:
            analysis = attempt.metadata.get("llm_analysis") if isinstance(attempt.metadata, dict) else None
            suggestions = analysis.get("learner_suggestions") if isinstance(analysis, dict) else None
            if isinstance(suggestions, list) and suggestions:
                return [str(item) for item in suggestions[:6] if str(item).strip()]
        return weak_points[:3] or profile.last_feedback_summary.get("recommended_topics", [])
