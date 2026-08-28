from app.db.feedback.base import BaseFeedbackRepository
from app.db.generation.base import BaseGenerationJobRepository
from app.db.learning_documents.base import BaseResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.services.learners.mastery import MasteryService
from app.models.learning_documents.types import SUPPORTED_RESOURCE_TYPES
from app.models.learners.mastery import MASTERY_CONFIRMATION_THRESHOLD
from app.models.reviews.claims import ClaimMetricStatus, ClaimVerdict, compute_claim_metric
from app.models.shared.workflow import normalize_review_status, review_status_is_approved
from app.models.reports.contracts import ReportRevisionPartsV1
from app.services.reports.difficulty_matching import STRATEGY_VERSION, match_difficulty
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
import hashlib
import json


# Increment this whenever a report's client-visible projection changes without
# any underlying learner fact changing.  It deliberately participates in the
# ETag/revision so a browser cannot retain a structurally stale report after a
# deployment (for example, the radar changing from measured nodes to the full
# knowledge graph).
REPORT_PROJECTION_VERSION = "4.2-weighted-accuracy"


class ReportSnapshotUnstable(RuntimeError):
    """A report read observed changing durable facts three times."""


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
        claim_repo=None,
        audit_repo=None,
        diagnosis_repo=None,
    ):
        self.resource_repo = resource_repo
        self.feedback_repo = feedback_repo
        self.feedback_loop_repo = feedback_loop_repo
        self.generation_job_repo = generation_job_repo
        self.mastery_service = mastery_service
        self.claim_repo = claim_repo
        self.audit_repo = audit_repo
        self.diagnosis_repo = diagnosis_repo

    def build_report(self, profile: LearnerProfile, *, window_days: int = 30, now: datetime | None = None) -> dict:
        for _ in range(3):
            report = self._build_report_once(profile, window_days=window_days, now=now)
            if self._snapshot_is_current(profile, report, window_days):
                return report
        raise ReportSnapshotUnstable("REPORT_SNAPSHOT_UNSTABLE")

    @staticmethod
    def _initial_diagnostic_flow(profile) -> dict:
        preferences = profile.learning_preferences
        metadata = preferences.metadata if preferences and isinstance(preferences.metadata, dict) else {}
        flow = metadata.get("initial_diagnostic_flow")
        return dict(flow) if isinstance(flow, dict) else {}

    @staticmethod
    def _initial_diagnostic_summary(flow: dict) -> dict:
        return {
            "questionnaire_tier": flow.get("questionnaire_tier"),
            "final_tier": flow.get("final_tier"),
            "initial_recommended_node_id": flow.get("initial_recommended_node_id"),
            "downgraded": flow.get("questionnaire_tier") != flow.get("final_tier"),
            "rounds": [
                {"tier": item.get("tier"), "node_ids": item.get("node_ids", []), "status": item.get("status")}
                for item in flow.get("rounds", []) if isinstance(item, dict)
            ],
        }

    def _latest_active_batch_target_ids(self, profile: LearnerProfile) -> set[str] | None:
        """Return the target nodes for the learner's newest effective batch.

        A curriculum row remains ``scheduled`` until publication reconciliation,
        so all scheduled rows cannot safely mean "current learning".  The
        generation-job record is the durable batch boundary and retains the
        adopted target snapshot for that batch.
        """
        if self.generation_job_repo is None:
            return None
        eligible_statuses = {"queued", "running", "completed"}
        jobs = [
            job for job in self.generation_job_repo.list_by_learner(profile.learner_id)
            if job.knowledge_base_id == profile.knowledge_base_id
            and job.job_status in eligible_statuses
            and not job.superseded_by_run_id
        ]
        if not jobs:
            return set()

        def created_key(job) -> float:
            created_at = job.created_at or job.started_at or job.finished_at
            return created_at.timestamp() if created_at is not None else float("-inf")

        latest = max(jobs, key=created_key)
        batch_id = latest.batch_id or latest.run_id
        target_ids: set[str] = set()
        for job in jobs:
            if (job.batch_id or job.run_id) != batch_id:
                continue
            payload = job.request_payload if isinstance(job.request_payload, dict) else {}
            constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
            snapshot = constraints.get("learner_focus_snapshot")
            candidates = (
                payload.get("target_skill_nodes")
                or constraints.get("target_skill_node_ids")
                or (snapshot.get("adopted_node_ids") if isinstance(snapshot, dict) else [])
            )
            for node_id in candidates:
                if node_id:
                    target_ids.add(str(node_id))
        # A batch may produce several resource variants and may target several
        # skills.  The graph's yellow state represents batch membership, so
        # retain every target from the newest effective batch.
        return target_ids

    @staticmethod
    def _assessment_conclusions(events, ability_projection) -> dict[str, dict]:
        """Expose why each node is, or is not yet, a trusted conclusion."""
        states = {
            node.skill_node_id: node.mastery
            for node in (ability_projection.nodes if ability_projection else [])
        }
        grouped: dict[str, list] = {}
        for event in events or []:
            if not event.verified or event.source_type.value not in {"diagnosis", "learning_attempt"}:
                continue
            if not getattr(event, "evidence_eligible", True):
                continue
            grouped.setdefault(event.skill_node_id, []).append(event)
        conclusions: dict[str, dict] = {}
        for node_id, state in states.items():
            node_events = sorted(grouped.get(node_id, []), key=lambda item: (item.occurred_at, item.evidence_id))
            sessions = {
                getattr(item, "assessment_session_id", None) or item.source_id
                for item in node_events
            }
            forms = {
                getattr(item, "assessment_form_id", None) or item.source_id
                for item in node_events
            }
            dimensions = sorted({
                dimension
                for item in node_events
                for dimension in getattr(item, "covered_dimensions", [])
            })
            scores = [item.observed_score for item in node_events if item.observed_score is not None]
            high_sessions = sum(score >= MASTERY_CONFIRMATION_THRESHOLD for score in scores)
            required_dimensions = {"concept", "scenario", "misconception"}
            initial_calibrated = any(
                item.source_type.value == "diagnosis"
                and required_dimensions.issubset(set(getattr(item, "covered_dimensions", [])))
                for item in node_events
            )
            cumulative_dimension_ready = required_dimensions.issubset(set(dimensions))
            dimension_ready = initial_calibrated or cumulative_dimension_ready
            qualified_high_events = [
                item for item in node_events
                if item.observed_score is not None and item.observed_score >= MASTERY_CONFIRMATION_THRESHOLD
            ]
            qualified_high_sessions = {
                getattr(item, "assessment_session_id", None) or item.source_id
                for item in qualified_high_events
            }
            if not node_events:
                conclusion, trust = "unassessed", "none"
            elif (
                state.status.value == "mastered"
                and dimension_ready
                and (
                    len(qualified_high_sessions) >= 2
                    or (
                        len(qualified_high_sessions) >= 1
                        and state.self_report_prior is not None
                        and state.self_report_prior >= 1.0
                    )
                )
            ):
                conclusion, trust = "confirmed_mastery", "high"
            elif len(sessions) < 2:
                conclusion, trust = "baseline_observation", "provisional"
            elif scores and scores[-1] < MASTERY_CONFIRMATION_THRESHOLD:
                conclusion, trust = "needs_reinforcement", "medium"
            else:
                conclusion, trust = "awaiting_confirmation", "medium"
            promotion_session_ids = list(dict.fromkeys(
                getattr(item, "assessment_session_id", None) or item.source_id
                for item in qualified_high_events
            ))[:2]
            promotion_index = max(
                (index for index, item in enumerate(node_events)
                 if (getattr(item, "assessment_session_id", None) or item.source_id) in promotion_session_ids),
                default=-1,
            )
            opposing = [
                {"source_id": item.source_id, "score": item.observed_score, "occurred_at": item.occurred_at}
                for item in node_events[promotion_index + 1:]
                if item.observed_score is not None and item.observed_score < MASTERY_CONFIRMATION_THRESHOLD
            ]
            conclusions[node_id] = {
                "conclusion": conclusion,
                "trust_status": trust,
                "formal_session_count": len(sessions),
                "independent_form_count": len(forms),
                "eligible_evidence_count": len(node_events),
                "high_score_session_count": high_sessions,
                "covered_dimensions": dimensions,
                "required_dimensions": ["concept", "scenario", "misconception"],
                "dimension_ready": dimension_ready,
                "initial_calibrated": initial_calibrated,
                "last_contradictory_evidence": opposing[-1] if opposing else None,
                "scoring_audit_statuses": list(dict.fromkeys(
                    getattr(item, "scoring_audit_status", "not_applicable") for item in node_events
                )),
            }
        return conclusions

    @staticmethod
    def _build_learning_node_mastery_map(ability_projection, assessment_conclusions, mastery_events=()) -> dict:
        """Build the ongoing node-level mastery view.

        Initial diagnostic dimensions are intentionally not projected here.
        This map is the stable report view for every learning node and is
        driven by the canonical mastery projection plus eligible formal
        assessment conclusions.
        """
        nodes = ReportService._ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
        priorities = {
            item.skill_node_id: item
            for item in (ability_projection.weakness_priorities if ability_projection else [])
        }
        events_by_node: dict[str, list] = {}
        for event in mastery_events or []:
            source_type = getattr(getattr(event, "source_type", None), "value", getattr(event, "source_type", None))
            if (
                getattr(event, "verified", False)
                and getattr(event, "evidence_eligible", True)
                and source_type in {"diagnosis", "learning_attempt"}
            ):
                events_by_node.setdefault(event.skill_node_id, []).append(event)

        points = []
        status_counts = {key: 0 for key in ("unassessed", "self_reported", "weak", "learning", "mastered")}
        conclusion_counts = {key: 0 for key in (
            "unassessed", "baseline_observation", "awaiting_confirmation", "confirmed_mastery", "needs_reinforcement"
        )}
        for node in nodes:
            state = node.mastery
            conclusion = (assessment_conclusions or {}).get(node.skill_node_id, {})
            conclusion_name = conclusion.get("conclusion", "unassessed")
            trust_status = conclusion.get("trust_status", "none")
            node_events = sorted(
                events_by_node.get(node.skill_node_id, []),
                key=lambda item: (ReportService._utc(item.occurred_at), item.evidence_id),
            )
            latest_event = node_events[-1] if node_events else None
            priority = priorities.get(node.skill_node_id)
            if conclusion_name in {"baseline_observation", "awaiting_confirmation"}:
                next_action = "verify"
            elif conclusion_name == "needs_reinforcement" or state.status.value == "weak":
                next_action = "remediate"
            elif conclusion_name == "confirmed_mastery" or state.status.value == "mastered":
                next_action = "maintain"
            elif state.status.value == "learning":
                next_action = "practice"
            else:
                next_action = "learn"
            reasons = list(priority.reason_codes) if priority else []
            if not reasons:
                reasons = {
                    "unassessed": ["NO_OBJECTIVE_EVIDENCE"],
                    "baseline_observation": ["INITIAL_BASELINE_PENDING_CONFIRMATION"],
                    "awaiting_confirmation": ["AWAITING_SECOND_FORMAL_ASSESSMENT"],
                    "confirmed_mastery": ["TWO_INDEPENDENT_FORMAL_ASSESSMENTS"],
                    "needs_reinforcement": ["LATEST_FORMAL_RESULT_BELOW_0_80"],
                }.get(conclusion_name, ["MASTERY_PROJECTION"])
            point = {
                "skill_node_id": node.skill_node_id,
                "name": node.name,
                "tier": node.tier,
                "tier_label": node.tier_label,
                "mastery_score": state.mastery_score,
                "mastery_status": state.status.value,
                "conclusion": conclusion_name,
                "trust_status": trust_status,
                "confidence": state.confidence.value,
                "objective_evidence_count": state.objective_evidence_count,
                "independent_session_count": conclusion.get("formal_session_count", 0),
                "independent_form_count": conclusion.get("independent_form_count", 0),
                "high_score_session_count": conclusion.get("high_score_session_count", 0),
                "latest_observed_score": latest_event.observed_score if latest_event else None,
                "trend_delta": node.trend_delta,
                "last_evidence_at": latest_event.occurred_at if latest_event else state.last_updated,
                "next_action": next_action,
                "reason_codes": reasons,
            }
            points.append(point)
            status_counts[state.status.value] += 1
            conclusion_counts[conclusion_name] += 1
        return {
            "schema_version": "1.0",
            "nodes": points,
            "summary": {
                **{f"status_{key}_count": value for key, value in status_counts.items()},
                **{f"conclusion_{key}_count": value for key, value in conclusion_counts.items()},
                "total_node_count": len(points),
                "actionable_node_count": sum(item["next_action"] != "maintain" for item in points),
            },
        }

    def _build_report_once(self, profile: LearnerProfile, *, window_days: int = 30, now: datetime | None = None) -> dict:
        """构建学情报告"""
        if window_days not in {7, 30, 90}:
            raise ValueError("window_days must be one of 7, 30, 90")
        generated_at = self._utc(now) if now is not None else datetime.now(timezone.utc)
        ability_projection = self.mastery_service.ability_nodes(profile) if self.mastery_service else None
        generation_options = (
            self.mastery_service.next_generation_options(profile)
            if self.mastery_service and profile.knowledge_base_id else None
        )
        ordered_nodes = self._ordered_ability_nodes(
            ability_projection.nodes if ability_projection else []
        )
        measured_nodes = [
            node for node in ordered_nodes
            if node.mastery.objective_evidence_count > 0 and node.mastery.mastery_score is not None
        ]
        # The radar is always the complete knowledge graph, even when a
        # legacy/partial ability projection is unavailable.  Questionnaire
        # theory fields must never replace graph-node axes.
        projected_by_id = {node.skill_node_id: node for node in ordered_nodes}
        catalog_nodes = (
            self.mastery_service.knowledge_service.list_skill_nodes(profile.knowledge_base_id)
            if self.mastery_service and profile.knowledge_base_id else []
        )
        radar_nodes = self._ordered_ability_nodes([
            SimpleNamespace(
                skill_node_id=node.node_id, name=node.name, tier=node.tier,
                prerequisites=node.prerequisites,
            )
            for node in catalog_nodes
        ])
        if not radar_nodes:
            radar_nodes = ordered_nodes
        topics = [node.name for node in radar_nodes]
        scores = []
        radar_measurement_statuses = []
        for node in radar_nodes:
            projected = projected_by_id.get(node.skill_node_id)
            measured = bool(
                projected and projected.mastery.objective_evidence_count > 0
                and projected.mastery.mastery_score is not None
            )
            self_reported = bool(
                projected and projected.mastery.status.value == "self_reported"
                and projected.mastery.mastery_score is not None
            )
            scores.append(
                round(float(projected.mastery.mastery_score) * 100, 1)
                if (measured or self_reported) else 0.0
            )
            radar_measurement_statuses.append(
                "measured" if measured else "self_reported" if self_reported else "unassessed"
            )
        resources = self._visible_resources(profile.learner_id)
        feedback = self.feedback_repo.list_by_learner(profile.learner_id)
        weak_points = ([node.name for node in measured_nodes if node.mastery.status.value == "weak"]
                       if ability_projection else list(dict.fromkeys(profile.weak_points)))
        strong_points = ([node.name for node in measured_nodes if node.mastery.status.value == "mastered"]
                         if ability_projection else list(dict.fromkeys(profile.strong_points)))
        # Aggregates must not silently become a "latest 10" view.  The UI
        # lists are bounded later; revision and activity consume all durable
        # formal attempts available from the repository.
        attempts = self.feedback_loop_repo.list_attempts(profile.learner_id, 10_000) if self.feedback_loop_repo else []
        diagnostic_runs = self.diagnosis_repo.list_runs_by_learner(profile.learner_id) if self.diagnosis_repo else []
        initial_flow = self._initial_diagnostic_flow(profile)
        loop_results = self.feedback_loop_repo.list_results(profile.learner_id, 10) if self.feedback_loop_repo else []
        # A server-scored formal feedback Attempt is already a durable,
        # learner-specific assessment fact.  It must make the report usable
        # even if an older initial-diagnostic flow was left pending/retest.
        calibration_pending = (
            initial_flow.get("status") in {"pending", "retest"}
            and not loop_results
        )
        visible_diagnostic_runs = [] if calibration_pending else diagnostic_runs
        diagnostic_measurements = self._diagnostic_measurements(visible_diagnostic_runs, ability_projection)
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
        # Subjective legacy rows may remain visible as history, but never feed
        # the verified activity metrics above.
        report_feedback = formal_feedback or feedback
        activity = self._learning_activity(attempts, generated_at, window_days)
        # Legacy subjective feedback never becomes a learning fact.  The
        # compatibility metric now mirrors the server-scored weighted result.
        report_average = activity["verified_accuracy"]
        path = self.feedback_loop_repo.get_current_path(profile.learner_id) if self.feedback_loop_repo else None
        versions = self.feedback_loop_repo.list_profile_versions(profile.learner_id, 10) if self.feedback_loop_repo else []
        mastery_events = (
            self.mastery_service.repository.list_events(profile.learner_id, profile.knowledge_base_id)
            if self.mastery_service and profile.knowledge_base_id else []
        )
        assessment_conclusions = self._assessment_conclusions(mastery_events, ability_projection)
        learning_node_mastery_map = self._build_learning_node_mastery_map(
            ability_projection, assessment_conclusions, mastery_events,
        )
        priorities = ability_projection.weakness_priorities if ability_projection else []
        ability_names = {
            node.skill_node_id: node.name for node in (ability_projection.nodes if ability_projection else [])
        }

        credibility = self._resource_credibility(resources, knowledge_base_id=profile.knowledge_base_id)
        blind_spot_map = self._build_blind_spot_map(ability_projection, attempts, visible_diagnostic_runs)
        resource_difficulty_curve = self._build_resource_difficulty_curve(
            ability_projection, resources, credibility_items=credibility["items"],
            credibility_summary=credibility["summary"], attempts=attempts,
        )
        current_batch_node_ids = self._latest_active_batch_target_ids(profile)
        learning_path_graph = self._build_learning_path_graph(
            ability_projection, path, generation_options, current_batch_node_ids=current_batch_node_ids,
        )
        revision_parts = self._revision_parts(
            profile, ability_projection, attempts, resources, window_days, credibility["items"], diagnostic_runs=visible_diagnostic_runs,
            resource_difficulty_curve=resource_difficulty_curve,
            learning_path_graph=learning_path_graph,
        )
        report_revision = self._revision(revision_parts, window_days)
        data_as_of = self._data_as_of(profile, attempts, resources, mastery_events)
        return {
            "report_schema_version": "4.1",
            "report_revision": report_revision,
            "data_as_of": data_as_of,
            "window": {
                "window_days": window_days,
                "start": activity["window_start"],
                "end": activity["window_end"],
            },
            "freshness": {"source_revisions": revision_parts, "warnings": []},
            "report_availability": {
                "status": "calibration_pending" if calibration_pending else "ready",
                "message": "初始诊断尚未完成，暂不生成正式学习结论" if calibration_pending else "报告已基于正式测评证据生成",
            },
            "learning_activity": activity,
            "mastery_overview": ability_projection.summary.model_dump(mode="json") if ability_projection else {},
            "mastery_trends": self._mastery_trends(mastery_events, ability_projection, generated_at, window_days),
            "weakness_groups": self._weakness_groups(priorities, ability_names),
            "resource_credibility_summary": credibility["summary"],
            "recent_resource_credibility": credibility["items"][:10],
            "as_of_profile_version": profile.profile_version,
            "generated_at": generated_at,
            "learner_id": profile.learner_id,
            "radar": {
                "dimensions": topics,
                "values": scores,
                "measurement_statuses": radar_measurement_statuses,
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
            "blind_spot_heatmap": ([
                {
                    "topic": node.name,
                    "score": round(float(node.mastery.mastery_score) * 100, 1) if node.mastery.mastery_score is not None else None,
                    "status": node.mastery.status.value,
                }
                for node in measured_nodes
                if node.mastery.status.value == "weak"
            ] if ability_projection else [
                {
                    "topic": point,
                    "score": profile.theory_scores.get(point, 0),
                    "status": profile.knowledge_states.get(point).status
                    if point in profile.knowledge_states
                    else "weak",
                }
                for point in weak_points
            ]),
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
            "recent_attempts": [item.model_dump(mode="json") for item in attempts[:10]],
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
            "ability_nodes": ordered_nodes if ability_projection else [],
            "mastery_summary": ability_projection.summary.model_dump(mode="json") if ability_projection else {},
            "assessment_conclusions": assessment_conclusions,
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
            "diagnostic_measurements": diagnostic_measurements,
            "initial_diagnostic": (self._initial_diagnostic_summary(initial_flow) if initial_flow.get("status") == "final" else {}),
            "weakness_priorities": priorities,
            "next_resource_focus": {
                "focus_mode": "auto",
                "adopted_node_ids": [item.skill_node_id for item in priorities[:3]],
                "reason_codes": {item.skill_node_id: item.reason_codes for item in priorities[:3]},
            },
            "generation_options": generation_options,
            "tier_progress": (
                generation_options.tier_progress.model_dump(mode="json")
                if generation_options and generation_options.tier_progress else {}
            ),
            "current_learning_state": {
                "active_tier": (
                    generation_options.tier_progress.active_tier
                    if generation_options and generation_options.tier_progress else None
                ),
                "current_node_ids": learning_path_graph.get("current_node_ids", []) if learning_path_graph else [],
                "recommended_next_node_ids": learning_path_graph.get("recommended_next_node_ids", []) if learning_path_graph else [],
                "selection_source": "confirmed_generation",
            },
            "knowledge_blind_spot_map": blind_spot_map,
            "learning_node_mastery_map": learning_node_mastery_map,
            "resource_difficulty_curve": resource_difficulty_curve,
            "learning_path_graph": learning_path_graph,
            "data_warnings": ability_projection.data_warnings if ability_projection else ["MASTERY_PROJECTION_UNAVAILABLE"],
        }

    def _snapshot_is_current(self, profile, report, window_days):
        projection = self.mastery_service.ability_nodes(profile) if self.mastery_service else None
        generation_options = (
            self.mastery_service.next_generation_options(profile)
            if self.mastery_service and profile.knowledge_base_id else None
        )
        attempts = self.feedback_loop_repo.list_attempts(profile.learner_id, 10_000) if self.feedback_loop_repo else []
        diagnostic_runs = self.diagnosis_repo.list_runs_by_learner(profile.learner_id) if self.diagnosis_repo else []
        if self._initial_diagnostic_flow(profile).get("status") in {"pending", "retest"}:
            diagnostic_runs = []
        resources = self._visible_resources(profile.learner_id)
        path = self.feedback_loop_repo.get_current_path(profile.learner_id) if self.feedback_loop_repo else None
        credibility = self._resource_credibility(resources, knowledge_base_id=profile.knowledge_base_id)
        current_parts = self._revision_parts(
            profile, projection, attempts, resources, window_days, credibility["items"], diagnostic_runs=diagnostic_runs,
            resource_difficulty_curve=self._build_resource_difficulty_curve(
                projection, resources, credibility_items=credibility["items"],
                credibility_summary=credibility["summary"], attempts=attempts,
            ),
            learning_path_graph=self._build_learning_path_graph(
                projection, path, generation_options,
                current_batch_node_ids=self._latest_active_batch_target_ids(profile),
            ),
        )
        return current_parts == report["freshness"]["source_revisions"]

    def _average_hallucination_rate(self, resources) -> float:
        values = [
            resource.claim_hallucination_rate
            for resource in resources
            if resource.resource_type in SUPPORTED_RESOURCE_TYPES
            and resource.claim_metric_status == "complete"
            and resource.claim_hallucination_rate is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)

    @staticmethod
    def _canonical_hash(value: object) -> str:
        encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _learning_activity(self, attempts, now: datetime, window_days: int) -> dict:
        end = now.astimezone(timezone.utc)
        start = end - timedelta(days=window_days)
        previous_start = start - timedelta(days=window_days)

        def aggregate(items):
            answered = sum(result.total_count for attempt in items for result in attempt.knowledge_point_results)
            correct = sum(result.correct_count for attempt in items for result in attempt.knowledge_point_results)
            weighted_score = 0.0
            weighted_max = 0.0
            for attempt in items:
                raw_metadata = getattr(attempt, "metadata", {})
                metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
                total_score = metadata.get("total_score")
                max_score = metadata.get("max_score")
                try:
                    if total_score is not None and max_score is not None and float(max_score) > 0:
                        weighted_score += float(total_score)
                        weighted_max += float(max_score)
                        continue
                except (TypeError, ValueError):
                    pass
                # Legacy attempts have no per-question score metadata. Their
                # point results are still an exact question-weighted fallback.
                for result in attempt.knowledge_point_results:
                    weighted_score += result.correct_count
                    weighted_max += result.total_count
            return correct, answered, weighted_score, weighted_max

        current = [item for item in attempts if start <= self._utc(item.submitted_at) < end]
        previous = [item for item in attempts if previous_start <= self._utc(item.submitted_at) < start]
        correct, answered, weighted_score, weighted_max = aggregate(current)
        previous_correct, previous_answered, previous_weighted_score, previous_weighted_max = aggregate(previous)
        accuracy = weighted_score / weighted_max if weighted_max else None
        previous_accuracy = previous_weighted_score / previous_weighted_max if previous_weighted_max else None
        return {
            "schema_version": "1.0", "status": "measured" if answered else "not_measured",
            "window_start": start, "window_end": end,
            "verified_attempt_count": len(current),
            "practiced_resource_count": len({item.source_resource_id for item in current}),
            "active_day_count": len({self._utc(item.submitted_at).date() for item in current}),
            "answered_item_count": answered, "correct_item_count": correct,
            "verified_accuracy": accuracy, "previous_period_accuracy": previous_accuracy,
            "accuracy_delta": accuracy - previous_accuracy if accuracy is not None and previous_accuracy is not None else None,
            "reason_codes": [] if answered else ["NO_VERIFIED_ATTEMPTS_IN_WINDOW"],
        }

    @staticmethod
    def _score_status(score: float) -> str:
        if score < 0.60:
            return "verified_weak"
        if score < MASTERY_CONFIRMATION_THRESHOLD:
            return "learning"
        return "mastered"

    @staticmethod
    def _ordered_ability_nodes(nodes):
        """Return a stable learning order: prerequisites first, then tier.

        Catalog storage order is not a learning sequence.  A Kahn traversal
        makes the dependency rule explicit; the tier/name key only resolves
        independent nodes at the same ready point.  Cycles remain visible in a
        deterministic tail instead of making the report fail to render.
        """
        by_id = {node.skill_node_id: node for node in nodes}
        child_ids = {node_id: [] for node_id in by_id}
        indegree = {node_id: 0 for node_id in by_id}
        for node in nodes:
            for prerequisite in node.prerequisites:
                if prerequisite not in by_id:
                    continue
                child_ids[prerequisite].append(node.skill_node_id)
                indegree[node.skill_node_id] += 1

        def sort_key(node_id: str):
            node = by_id[node_id]
            tier = getattr(node, "tier", None)
            # Within one tier, show a prerequisite that unlocks downstream
            # learning before an unrelated peer.  This makes the horizontal
            # report order useful as a study path, not merely alphabetical.
            return (int(tier) if tier is not None else 99, -len(child_ids[node_id]), node.name, node_id)

        ready = sorted((node_id for node_id, degree in indegree.items() if degree == 0), key=sort_key)
        ordered_ids = []
        while ready:
            node_id = ready.pop(0)
            ordered_ids.append(node_id)
            for child_id in sorted(child_ids[node_id], key=sort_key):
                indegree[child_id] -= 1
                if indegree[child_id] == 0:
                    ready.append(child_id)
            ready.sort(key=sort_key)
        ordered_ids.extend(sorted((node_id for node_id in by_id if node_id not in set(ordered_ids)), key=sort_key))
        return [by_id[node_id] for node_id in ordered_ids]

    def _build_blind_spot_map(self, ability_projection, attempts, diagnostic_runs=()) -> dict:
        """Project only dimension evidence that can be reconstructed exactly.

        A point-level attempt result can cover several questions.  If its stored
        trace spans more than one dimension, the aggregate score cannot be
        honestly split across those dimensions, so the relevant cells stay in
        an evidence-needed state instead of copying the node score.
        """
        dimensions = ["concept", "scenario", "misconception", "practice"]
        nodes = self._ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
        node_ids = {item.skill_node_id for item in nodes}
        exact_scores: dict[tuple[str, str], tuple[datetime, str, float]] = {}
        pending_diagnostic_cells: set[tuple[str, str]] = set()
        # Initial direction diagnosis is a formal server-scored source too.
        # Its trace is deliberately de-identified: no learner answer, answer
        # key, or explanation is needed to render a blind-spot cell.
        for run in diagnostic_runs:
            raw = run.raw_result if isinstance(run.raw_result, dict) else {}
            submitted_at = self._utc(run.created_at) if run.created_at else datetime.min.replace(tzinfo=timezone.utc)
            for item in raw.get("blind_spot_trace", []):
                if not isinstance(item, dict):
                    continue
                node_id = item.get("skill_node_id")
                dimension = item.get("diagnostic_dimension")
                if node_id not in node_ids or dimension not in dimensions or not isinstance(item.get("correct"), bool):
                    continue
                key = (node_id, dimension)
                if item.get("measurement_status") != "measured":
                    pending_diagnostic_cells.add(key)
                    continue
                candidate = (submitted_at, f"diagnosis:{run.diagnostic_result_id}", 1.0 if item["correct"] else 0.0)
                if key not in exact_scores or candidate[:2] > exact_scores[key][:2]:
                    exact_scores[key] = candidate
        for attempt in attempts:
            trace = attempt.metadata.get("question_trace", []) if isinstance(attempt.metadata, dict) else []
            trace_by_question = {
                str(item.get("question_id")): item for item in trace
                if isinstance(item, dict) and item.get("question_id")
            }
            for result in attempt.knowledge_point_results:
                entries = [trace_by_question.get(question_id) for question_id in result.question_ids]
                if not entries or any(entry is None for entry in entries):
                    continue
                pairs = {
                    (str(entry.get("skill_node_id")), str(entry.get("diagnostic_dimension")))
                    for entry in entries
                    if entry.get("skill_node_id") in node_ids and entry.get("diagnostic_dimension") in dimensions
                }
                if len(pairs) != 1:
                    continue
                node_id, dimension = pairs.pop()
                observed = result.correct_count / result.total_count
                key = (node_id, dimension)
                candidate = (self._utc(attempt.submitted_at), attempt.attempt_id, observed)
                if key not in exact_scores or candidate[:2] > exact_scores[key][:2]:
                    exact_scores[key] = candidate

        cells = []
        node_states = {}
        for node in nodes:
            state = node.mastery
            statuses = []
            has_dimension_score = any(
                (node.skill_node_id, dimension) in exact_scores for dimension in dimensions
            )
            for dimension in dimensions:
                evidence = exact_scores.get((node.skill_node_id, dimension))
                if evidence is not None:
                    score = round(evidence[2], 6)
                    status = self._score_status(score)
                    reasons = ["FORMAL_DIMENSION_EVIDENCE"]
                elif (node.skill_node_id, dimension) in pending_diagnostic_cells:
                    score = None
                    status = "needs_evidence"
                    reasons = ["DIAGNOSTIC_COVERAGE_INCOMPLETE"]
                elif (
                    dimension == "concept"
                    and not has_dimension_score
                    and state.objective_evidence_count > 0
                    and state.mastery_score is not None
                ):
                    # Older generated-resource assessments recorded a verified
                    # node score but did not label each question with a
                    # diagnostic dimension.  Surface that real aggregate in
                    # one clearly bounded cell rather than reporting the whole
                    # node as unmeasured; do not copy it into other dimensions.
                    score = round(float(state.mastery_score), 6)
                    status = self._score_status(score)
                    reasons = ["FORMAL_NODE_EVIDENCE_NO_DIMENSION"]
                elif state.objective_evidence_count > 0:
                    score = None
                    status = "needs_evidence"
                    reasons = ["DIMENSION_EVIDENCE_UNAVAILABLE"]
                elif state.status.value == "self_reported":
                    score = None
                    status = "needs_evidence"
                    reasons = ["LOW_CONFIDENCE_SELF_REPORT"]
                else:
                    score = None
                    status = "unassessed"
                    reasons = ["NO_OBJECTIVE_EVIDENCE"]
                statuses.append(status)
                cells.append({
                    "skill_node_id": node.skill_node_id,
                    "dimension": dimension,
                    "score": score,
                    "status": status,
                    "confidence": state.confidence.value,
                    "objective_evidence_count": state.objective_evidence_count,
                    "reason_codes": reasons,
                })
            node_states[node.skill_node_id] = statuses

        def node_status(statuses):
            if "verified_weak" in statuses:
                return "verified_weak"
            if "learning" in statuses:
                return "learning"
            if "mastered" in statuses:
                return "mastered"
            if "needs_evidence" in statuses:
                return "needs_evidence"
            return "unassessed"

        counts = {key: 0 for key in ("verified_weak", "learning", "mastered", "needs_evidence", "unassessed")}
        for statuses in node_states.values():
            counts[node_status(statuses)] += 1
        measured = sum(1 for statuses in node_states.values() if any(status in {"verified_weak", "learning", "mastered"} for status in statuses))
        return {
            "schema_version": "1.0",
            "dimensions": dimensions,
            "nodes": [
                {"skill_node_id": node.skill_node_id, "name": node.name, "stable_order": index,
                 "prerequisite_ids": list(node.prerequisites)}
                for index, node in enumerate(nodes, start=1)
            ],
            "cells": cells,
            "summary": {
                **{f"{key}_count": value for key, value in counts.items()},
                "measurement_coverage": measured / len(nodes) if nodes else None,
                "measured_node_count": measured,
                "total_node_count": len(nodes),
            },
        }

    @staticmethod
    def _diagnostic_measurements(diagnostic_runs, ability_projection) -> dict:
        """Return only the latest safe coverage summary for each node."""
        result: dict[str, dict] = {}
        for run in sorted(
            diagnostic_runs,
            key=lambda item: (ReportService._utc(item.created_at) if item.created_at else datetime.min.replace(tzinfo=timezone.utc), item.diagnostic_result_id),
        ):
            raw = run.raw_result if isinstance(run.raw_result, dict) else {}
            for node_id, summary in (raw.get("measurement_coverage", {}) or {}).items():
                if isinstance(summary, dict):
                    result[node_id] = dict(summary)
        for node in (ability_projection.nodes if ability_projection else []):
            item = result.get(node.skill_node_id)
            if item is not None:
                item["formal_evidence_count"] = node.mastery.objective_evidence_count
        return result

    def _build_resource_difficulty_curve(
        self, ability_projection, resources, *, credibility_items=None, credibility_summary=None, attempts=None,
    ) -> dict:
        ordered_nodes = self._ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
        node_order = {item.skill_node_id: index for index, item in enumerate(ordered_nodes)}
        nodes = {item.skill_node_id: item for item in ordered_nodes}
        credibility_by_resource = {
            (item["resource_id"], item.get("resource_version")): item
            for item in (credibility_items or [])
        }
        feedback_by_resource = {}
        for attempt in attempts or []:
            resource_id = getattr(attempt, "source_resource_id", None)
            score = getattr(attempt, "overall_score", None)
            if resource_id and isinstance(score, (int, float)) and 0 <= score <= 1:
                key = (resource_id, getattr(attempt, "source_resource_version", 1))
                feedback_by_resource.setdefault(key, []).append(float(score))

        def calibrated_match(match, feedback_scores):
            """Raise difficulty only when formal feedback is below 60%."""
            if match.score is None or match.gap is None or not feedback_scores:
                return match, None, 0.0
            feedback_score = sum(feedback_scores) / len(feedback_scores)
            if feedback_score >= 0.60:
                return match, feedback_score, 0.0
            # Readiness provides context so an unprepared learner's low score
            # does not overstate the resource's actual difficulty.
            low_score_signal = (0.60 - feedback_score) * 0.20
            readiness_signal = max(0.0, match.gap) * 0.25
            adjustment = round(min(0.20, max(low_score_signal, readiness_signal)), 6)
            score = min(1.0, round(match.score + adjustment, 6))
            gap = round(score - (match.score - match.gap), 6)
            if gap < -0.15:
                status = "too_easy"
            elif gap <= 0.10:
                status = "matched"
            elif gap <= 0.25:
                status = "challenging"
            else:
                status = "too_hard"
            return match.__class__(
                score, "calibrated_history", gap, status,
                ("DIFFICULTY_CALIBRATED_FROM_LOW_FEEDBACK",),
            ), feedback_score, adjustment

        resource_points = []
        for resource in resources:
            if resource.publication_status != "published":
                continue
            target_ids = []
            if resource.learning_path_node in nodes:
                target_ids.append(resource.learning_path_node)
            target_ids.extend(point for point in resource.knowledge_points if point in nodes and point not in target_ids)
            if not target_ids:
                continue
            credibility = credibility_by_resource.get((resource.resource_id, resource.version))
            # A resource is rendered once.  Prefer its explicit learning-path
            # target; the first linked node is a deterministic legacy fallback.
            node_id = target_ids[0] if target_ids else None
            node = nodes.get(node_id) if node_id else None
            readiness = (
                node.mastery.mastery_score
                if node and node.mastery.objective_evidence_count > 0 else None
            )
            match = match_difficulty(learner_readiness=readiness, declared_difficulty=resource.difficulty)
            feedback_scores = feedback_by_resource.get((resource.resource_id, resource.version), [])
            adjusted_match, feedback_score, difficulty_adjustment = calibrated_match(match, feedback_scores)
            resource_points.append({
                "resource_id": resource.resource_id,
                "skill_node_id": node_id or "unassigned",
                "skill_name": node.name if node else "未关联能力节点",
                "point_type": "resource",
                "batch_id": resource.batch_id or resource.run_id,
                "_batch_key": resource.batch_id or resource.run_id or "__legacy__",
                "resource_name": resource.topic or resource.resource_type,
                "resource_count": 1,
                "default_resource_difficulty_score": match.score,
                "learner_readiness_score": readiness,
                "resource_difficulty_score": adjusted_match.score,
                "difficulty_gap": adjusted_match.gap,
                "match_status": adjusted_match.status,
                "confidence": node.mastery.confidence.value if node else "none",
                "difficulty_source": adjusted_match.source,
                "resource_type": resource.resource_type,
                "resource_ids": [resource.resource_id],
                "reason_codes": list(adjusted_match.reason_codes),
                "feedback_score": feedback_score,
                "feedback_count": len(feedback_scores),
                "difficulty_adjustment": difficulty_adjustment,
                "credibility_score": credibility.get("credibility_score") if credibility else None,
                "credibility_level": credibility.get("credibility_level") if credibility else None,
                "credibility_grade": credibility.get("grade") if credibility else None,
                "credibility_score_breakdown": credibility.get("score_breakdown") if credibility else None,
                "_published_at": resource.published_at or resource.created_at,
            })

        batches = {}
        for point in resource_points:
            batches.setdefault(point["_batch_key"], []).append(point)

        def batch_time(items):
            dates = [item["_published_at"] for item in items if item["_published_at"] is not None]
            return max((self._utc(value) for value in dates), default=datetime.min.replace(tzinfo=timezone.utc))

        ordered_batches = sorted(batches.items(), key=lambda item: (batch_time(item[1]), str(item[0])))
        latest_batch_id = ordered_batches[-1][0] if ordered_batches else None

        def average(items, key):
            values = [item[key] for item in items if isinstance(item.get(key), (int, float))]
            return round(sum(values) / len(values), 6) if values else None

        def aggregate_batch(batch_id, items):
            readiness = average(items, "learner_readiness_score")
            difficulty = average(items, "resource_difficulty_score")
            gap = average(items, "difficulty_gap")
            calibrated = any(item["difficulty_source"] == "calibrated_history" for item in items)
            if readiness is None or difficulty is None or gap is None:
                status = "not_measured"
                source = "unavailable" if difficulty is None else "calibrated_history" if calibrated else "declared_band"
            elif gap < -0.15:
                status = "too_easy"
                source = "calibrated_history" if calibrated else "declared_band"
            elif gap <= 0.10:
                status = "matched"
                source = "calibrated_history" if calibrated else "declared_band"
            elif gap <= 0.25:
                status = "challenging"
                source = "calibrated_history" if calibrated else "declared_band"
            else:
                status = "too_hard"
                source = "calibrated_history" if calibrated else "declared_band"
            reason_codes = ["BATCH_AVERAGE"]
            if calibrated:
                reason_codes.append("BATCH_INCLUDES_FEEDBACK_CALIBRATION")
            scores = [item["credibility_score"] for item in items if isinstance(item.get("credibility_score"), (int, float))]
            return {
                "resource_id": f"batch:{batch_id}",
                "skill_node_id": f"batch:{batch_id}",
                "skill_name": "历史批次平均",
                "point_type": "batch_average",
                "batch_id": None if batch_id == "__legacy__" else batch_id,
                "resource_name": "历史资源批次",
                "resource_count": len({resource_id for item in items for resource_id in item["resource_ids"]}),
                "default_resource_difficulty_score": average(items, "default_resource_difficulty_score"),
                "learner_readiness_score": readiness,
                "resource_difficulty_score": difficulty,
                "difficulty_gap": gap,
                "match_status": status,
                "confidence": "batch_average",
                "difficulty_source": source,
                "resource_type": "批次平均",
                "resource_ids": list(dict.fromkeys(resource_id for item in items for resource_id in item["resource_ids"])),
                "reason_codes": reason_codes,
                "feedback_score": average(items, "feedback_score"),
                "feedback_count": sum(item.get("feedback_count", 0) for item in items),
                "difficulty_adjustment": average(items, "difficulty_adjustment"),
                "credibility_score": average(items, "credibility_score"),
                "credibility_level": "batch_average" if scores else None,
                "credibility_grade": None,
                "credibility_score_breakdown": None,
            }

        points = []
        for batch_key, items in ordered_batches:
            if batch_key == latest_batch_id:
                points.extend(sorted(
                    items,
                    key=lambda item: (node_order.get(item["skill_node_id"], len(node_order)), item["resource_id"]),
                ))
            else:
                points.append(aggregate_batch(batch_key, items))
        for point in points:
            point.pop("_published_at", None)
            point.pop("_batch_key", None)
        counts = {key: 0 for key in ("too_easy", "matched", "challenging", "too_hard", "not_measured")}
        for point in points:
            counts[point["match_status"]] += 1
        measured = len(points) - counts["not_measured"]
        resource_count = len(resource_points)
        return {
            "schema_version": "1.0",
            "strategy_version": STRATEGY_VERSION,
            "points": points,
            "summary": {
                "total_point_count": len(points),
                "total_resource_count": resource_count,
                "batch_count": len(ordered_batches),
                "expanded_resource_count": sum(len(items) for batch_id, items in ordered_batches if batch_id == latest_batch_id),
                "aggregated_batch_count": max(0, len(ordered_batches) - 1),
                "measured_point_count": measured,
                "measurement_coverage": measured / len(points) if points else None,
                "credibility_strategy_version": (credibility_summary or {}).get("scoring_strategy_version"),
                "credibility_scored_count": (credibility_summary or {}).get("scored_count", 0),
                "average_credibility_score": (credibility_summary or {}).get("average_credibility_score"),
                "claim_review_passed_count": (credibility_summary or {}).get("claim_review_passed_count", 0),
                "claim_ceiling_applied_count": (credibility_summary or {}).get("claim_ceiling_applied_count", 0),
                **{f"{key}_count": value for key, value in counts.items()},
            },
        }

    def _build_learning_path_graph(
        self, ability_projection, path, generation_options, *, current_batch_node_ids: set[str] | None = None,
    ) -> dict:
        nodes = self._ordered_ability_nodes(ability_projection.nodes if ability_projection else [])
        known_ids = {item.skill_node_id for item in nodes}
        curriculum = {
            item.skill_node_id: item for item in (ability_projection.curriculum_nodes if ability_projection else [])
        }
        path_nodes = {}
        for item in (path.nodes if path else []):
            if item.knowledge_point_id in known_ids:
                path_nodes[item.knowledge_point_id] = item
        recommended_ids = set(generation_options.recommended_node_ids if generation_options else [])
        remedial_ids = {
            item.skill_node_id for item in (generation_options.reinforce_weakness if generation_options else [])
        }
        new_ids = {
            item.skill_node_id for item in (generation_options.learn_new_knowledge if generation_options else [])
        }
        # Only the newest effective generation batch defines "current
        # learning".  If that batch projection is unavailable, do not infer
        # currentness from mastery or curriculum status: those facts describe
        # learner progress, not membership in the latest round.
        current_ids = set(current_batch_node_ids or ())
        tier_progress = getattr(generation_options, "tier_progress", None) if generation_options else None
        highest_unlocked_tier = getattr(tier_progress, "highest_unlocked_tier", None)

        graph_nodes = []
        for index, node in enumerate(nodes, start=1):
            path_node = path_nodes.get(node.skill_node_id)
            progress = curriculum.get(node.skill_node_id)
            missing = [
                prerequisite for prerequisite in node.prerequisites
                if prerequisite in known_ids and (curriculum.get(prerequisite) is None or curriculum[prerequisite].published_resource_count <= 0)
            ]
            tier_locked = bool(
                highest_unlocked_tier is not None
                and node.tier is not None
                and node.tier > highest_unlocked_tier
            )
            placement_exempt = bool(progress and progress.placement_exempt and not progress.placement_verification_required)
            learning_history = bool(progress and (
                progress.published_resource_count > 0
                or progress.verified_attempt_count > 0
                or progress.progress_status.value in {"exposed", "verification_pending", "reinforcement_due", "completed"}
            ))
            # Placement has already covered lower tiers.  These nodes are not
            # formally completed, but they must not be presented as blocked
            # just because no learning batch was generated for them.
            # Likewise, a node that has already been published or assessed
            # retains its learning outcome when the learner temporarily
            # returns to a prerequisite tier. It is historical progress, not
            # a newly blocked future node.
            blocked = (
                not placement_exempt
                and not learning_history
                and (bool(missing) or tier_locked or bool(path_node and path_node.status.value == "locked"))
            )
            if node.skill_node_id in current_ids:
                role = "current"
            elif node.skill_node_id in remedial_ids:
                # Only the server's eligible "learned but not mastered" set is
                # actionable remediation. A weak diagnosis alone does not mean
                # the learner has first received this node's learning resource.
                role = "remedial"
            elif path_node and path_node.node_type.value == "challenge":
                role = "challenge"
            elif path_node and path_node.node_type.value == "remedial":
                role = "remedial"
            elif node.skill_node_id in recommended_ids or node.skill_node_id in new_ids:
                role = "next"
            elif node.mastery.status.value == "weak" and generation_options is None:
                # Retain the legacy read-only projection for report callers
                # that do not have the generation-option service wired.
                role = "remedial"
            elif node.mastery.status.value in {"unassessed", "self_reported"}:
                role = "verification"
            else:
                role = "prerequisite"
            reason_codes = []
            if node.mastery.status.value == "weak":
                reason_codes.append("OBJECTIVE_SCORE_BELOW_0_60")
            if node.mastery.status.value == "self_reported":
                reason_codes.append("LOW_CONFIDENCE_SELF_REPORT")
            if missing:
                reason_codes.append("PREREQUISITES_NOT_YET_EXPOSED")
            if tier_locked:
                reason_codes.append("TIER_NOT_UNLOCKED")
            if placement_exempt:
                reason_codes.append("PLACEMENT_EXEMPT")
            if path_node:
                reason_codes.append(f"PATH_NODE_{path_node.node_type.value.upper()}")
            resource_types = (
                ["讲义", "实操指南", "分阶测试题"] if role == "remedial"
                else ["复习清单", "实操指南", "分阶测试题"] if role == "current"
                else ["案例分析", "分阶测试题"] if role == "challenge"
                else ["分阶测试题"] if role == "verification"
                else ["讲义", "复习清单"]
            )
            graph_nodes.append({
                "skill_node_id": node.skill_node_id,
                "name": node.name,
                "progress_status": progress.progress_status.value if progress else (path_node.status.value if path_node else "unplanned"),
                "placement_verification_status": (
                    "verification_required" if progress and progress.placement_verification_required
                    else "placement_exempt" if progress and progress.placement_exempt
                    else "formally_reverified" if progress and progress.placement_evidence_id
                    else "not_applicable"
                ),
                "placement_exempt": placement_exempt,
                "mastery_status": node.mastery.status.value,
                "mastery_score": node.mastery.mastery_score,
                "confidence": node.mastery.confidence.value,
                "role": role,
                "is_current_batch": node.skill_node_id in current_ids,
                "blocked": blocked,
                "blocked_by_node_ids": missing,
                "recommended_resource_types": resource_types,
                "reason_codes": reason_codes or ["KNOWLEDGE_GRAPH_POSITION"],
                "stable_order": index,
                "tier": node.tier,
                "prerequisite_ids": [item for item in node.prerequisites if item in known_ids],
            })
        edges = [
            {"source_skill_node_id": edge["from"], "target_skill_node_id": edge["to"], "relation": "prerequisite"}
            for edge in (ability_projection.edges if ability_projection else [])
            if edge.get("from") in known_ids and edge.get("to") in known_ids and edge.get("from") != edge.get("to")
        ]
        order_by_id = {item["skill_node_id"]: item["stable_order"] for item in graph_nodes}
        edges.sort(key=lambda item: (
            order_by_id[item["source_skill_node_id"]],
            order_by_id[item["target_skill_node_id"]],
        ))
        # "Focus" is the learner-facing projection of the newest generation
        # batch.  Do not include merely recommended next nodes here: they are
        # available choices for a future batch, not part of this round.
        focus_ids = [
            item["skill_node_id"]
            for item in graph_nodes
            if item["skill_node_id"] in current_ids
        ]
        return {
            "schema_version": "1.0",
            "path_id": path.path_id if path else None,
            "path_version": path.version if path else None,
            "nodes": graph_nodes,
            "edges": edges,
            "current_node_ids": sorted(current_ids),
            "recommended_next_node_ids": sorted(recommended_ids),
            "focus_node_ids": focus_ids,
            "summary": {
                "total_node_count": len(graph_nodes),
                "blocked_node_count": sum(item["blocked"] for item in graph_nodes),
                "remedial_node_count": sum(item["role"] == "remedial" for item in graph_nodes),
                "eligible_remedial_node_count": len(remedial_ids),
                "verification_node_count": sum(item["role"] == "verification" for item in graph_nodes),
                "next_node_count": sum(item["role"] == "next" for item in graph_nodes),
            },
        }

    def _revision_parts(
        self, profile, ability_projection, attempts, resources, window_days, credibility_items=None,
        *, resource_difficulty_curve=None, learning_path_graph=None, diagnostic_runs=(),
    ):
        flow = self._initial_diagnostic_flow(profile)
        calibration_pending = flow.get("status") in {"pending", "retest"}
        profile_part = {"learner_id": profile.learner_id, "knowledge_base_id": profile.knowledge_base_id,
                        "profile_version": "initial_calibration_pending" if calibration_pending else profile.profile_version,
                        "skill_level": profile.skill_level,
                        "learning_goal": profile.learning_goal}
        mastery_part = [node.model_dump(mode="json") for node in sorted((ability_projection.nodes if ability_projection else []), key=lambda item: item.skill_node_id)]
        activity_part = [{"id": item.attempt_id, "submitted_at": item.submitted_at, "results": [x.model_dump(mode="json") for x in item.knowledge_point_results],
                          "assessment": {key: item.metadata.get(key) for key in ("assessment_kind", "assessment_session_id", "assessment_form_id", "scoring_audit")},
                          "question_trace": [{key: trace.get(key) for key in ("question_id", "skill_node_id", "diagnostic_dimension")} for trace in item.metadata.get("question_trace", []) if isinstance(trace, dict)]}
                         for item in sorted(attempts, key=lambda item: (self._utc(item.submitted_at), item.attempt_id))]
        activity_part.append({"diagnostic_traces": [
            {"id": run.diagnostic_result_id, "created_at": run.created_at,
             "trace": (run.raw_result or {}).get("blind_spot_trace", [])}
            for run in sorted(diagnostic_runs, key=lambda run: (self._utc(run.created_at) if run.created_at else datetime.min.replace(tzinfo=timezone.utc), run.diagnostic_result_id))
        ]})
        resource_part = [{"id": item.resource_id, "version": item.version, "publication": item.publication_status,
                          "review": item.review_status, "review_id": item.review_id, "claim_metric": item.claim_metric_status,
                          "claim_rate": item.claim_hallucination_rate, "refs": [ref.model_dump(mode="json") for ref in sorted(item.source_refs, key=lambda ref: (ref.evidence_id or "", ref.doc_id, ref.chunk_id or ""))]}
                         for item in sorted(resources, key=lambda item: (item.resource_id, item.version))]
        # Review issues and immutable Claim/Judgement verdicts live in their
        # own repositories.  Projecting only their safe credibility summary
        # ensures a quality correction changes revision even when the profile
        # version is deliberately unchanged.
        if credibility_items is not None:
            resource_part.append({"credibility": credibility_items})
        return ReportRevisionPartsV1(
            profile=self._canonical_hash(profile_part),
            mastery=self._canonical_hash(mastery_part),
            activity=self._canonical_hash(activity_part),
            text_resources=self._canonical_hash(resource_part),
            resource_match=self._canonical_hash(resource_difficulty_curve or {}),
            path=self._canonical_hash(learning_path_graph or {}),
        ).model_dump()

    def _revision(self, parts, window_days):
        return "rpt_" + self._canonical_hash({
            "parts": parts,
            "window_days": window_days,
            "projection_version": REPORT_PROJECTION_VERSION,
        })

    @staticmethod
    def _data_as_of(profile, attempts, resources, events):
        values = [item for item in [getattr(profile, "updated_at", None)] if item]
        values.extend(item.submitted_at for item in attempts if item.submitted_at)
        values.extend(item.published_at or item.created_at for item in resources if item.published_at or item.created_at)
        values.extend(item.occurred_at for item in events if item.occurred_at)
        normalized = [ReportService._utc(value) for value in values]
        return max(normalized) if normalized else None

    @staticmethod
    def _utc(value: datetime) -> datetime:
        """SQLite returns naive timestamps; persisted timestamps are UTC."""
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    @staticmethod
    def _weakness_groups(priorities, ability_names):
        groups = {"verified_weak": [], "regressing_learning": [], "needs_evidence": []}
        mapping = {"confirmed_weak": "verified_weak", "regressing_learning": "regressing_learning",
                   "low_self_report": "needs_evidence", "blocked_uncovered": "needs_evidence"}
        for item in priorities:
            group = mapping.get(item.priority_group)
            if group is None:
                # Ready/uncovered and maintained nodes belong to the explicit
                # next-generation candidates, not the evidence-risk groups.
                continue
            groups[group].append({"skill_node_id": item.skill_node_id, "name": ability_names.get(item.skill_node_id, item.skill_node_id),
                                  "reason_codes": item.reason_codes, "mastery_score": item.mastery_score,
                                  "confidence": item.confidence.value})
        return groups

    @staticmethod
    def _mastery_trends(events, projection, now, window_days):
        start = now - timedelta(days=window_days)
        names = {item.skill_node_id: item.name for item in (projection.nodes if projection else [])}
        result = {}
        previous_objective = {}
        for event in sorted(events, key=lambda item: (ReportService._utc(item.occurred_at), item.evidence_id)):
            if ReportService._utc(event.occurred_at) < start:
                continue
            before = previous_objective.get(event.skill_node_id) if event.verified else None
            point = {"event_id": event.evidence_id, "before_score": before, "after_score": event.after_state.mastery_score,
                     "delta": (event.after_state.mastery_score - before) if before is not None and event.after_state.mastery_score is not None else None,
                     "source_type": event.source_type.value, "verified": event.verified, "occurred_at": ReportService._utc(event.occurred_at)}
            if event.verified:
                previous_objective[event.skill_node_id] = event.after_state.mastery_score
            result.setdefault(event.skill_node_id, []).append(point)
        return [{"schema_version": "1.0", "skill_node_id": node_id, "name": names.get(node_id, node_id), "points": points}
                for node_id, points in sorted(result.items())]

    def _resource_credibility(self, resources, *, knowledge_base_id: str | None = None):
        items = []
        for resource in resources:
            if resource.publication_status != "published" or str(resource.representation) not in {"text", "ResourceRepresentation.TEXT"} or resource.resource_type not in SUPPORTED_RESOURCE_TYPES:
                continue
            review = self.audit_repo.get_review_by_resource(resource.resource_id) if self.audit_repo else None
            review_matches = bool(review and review.review_id == resource.review_id)
            review_status_value = normalize_review_status(
                review.status if review_matches else resource.review_status,
            )
            issues = review.issues if review_matches else []
            blocking_count = sum(str(issue.get("severity", "")).lower() in {"high", "critical"} for issue in issues)
            review_passed = review_matches and review_status_is_approved(review_status_value) and not blocking_count
            blocking = review_status_value in {"rejected", "human_review", "revision_requested"} or bool(blocking_count)
            review_status = "failed" if blocking else "passed" if review_passed else "not_measured"
            claims, judgements = self._claims_for_resource(resource)
            if claims:
                computed = compute_claim_metric(claims, judgements)
                metric = computed.metric_status.value
                unsupported_rate = computed.claim_hallucination_rate
                claim_status = "failed" if metric == ClaimMetricStatus.COMPLETE.value and (computed.contradicted_claim_total or computed.not_in_evidence_claim_total) else "passed" if metric == ClaimMetricStatus.COMPLETE.value else "not_applicable" if metric == ClaimMetricStatus.NOT_APPLICABLE.value else "not_measured"
                claim_counts = {"factual_claim_count": computed.factual_claim_total, "supported_claim_count": computed.supported_claim_total,
                                "contradicted_claim_count": computed.contradicted_claim_total, "not_in_evidence_claim_count": computed.not_in_evidence_claim_total,
                                "incomplete_claim_count": computed.incomplete_claim_total}
            else:
                metric = resource.claim_metric_status if resource.claim_metric_status == ClaimMetricStatus.NOT_APPLICABLE.value else "legacy_unavailable"
                unsupported_rate = None
                claim_status = "not_applicable" if metric == ClaimMetricStatus.NOT_APPLICABLE.value else "not_measured"
                claim_counts = {"factual_claim_count": 0, "supported_claim_count": 0, "contradicted_claim_count": 0, "not_in_evidence_claim_count": 0, "incomplete_claim_count": 0}
            refs = resource.source_refs or []
            verified = [ref for ref in refs if ref.provenance_status == "verified" and ref.evidence_id and ref.knowledge_base_id and ref.doc_id and ref.document_version and ref.chunk_id]
            # A knowledge-base mismatch is an explicit provenance failure,
            # rather than a merely incomplete legacy reference.  Detailed
            # Evidence existence is intentionally not guessed without a
            # repository-backed evidence record.
            cross_knowledge_base = bool(knowledge_base_id and any(
                ref.knowledge_base_id and ref.knowledge_base_id != knowledge_base_id
                for ref in refs
            ))
            trace_status = "failed" if cross_knowledge_base else "passed" if refs and len(verified) == len(refs) else "partial" if verified else "not_measured"
            review_score = (
                0.0 if blocking
                else 40.0 if review_passed and not issues
                else 30.0 if review_passed
                else 10.0
            )
            review_score_status = (
                "failed" if blocking else "passed" if review_passed and not issues
                else "passed_with_issues" if review_passed else "not_measured"
            )
            trace_score = 0.0 if cross_knowledge_base or not refs else round(50.0 * len(verified) / len(refs), 1)
            claim_passed = claim_status == "passed"
            claim_score = 10.0 if claim_passed else 0.0
            score_ceiling = 99.0 if claim_passed else 80.0
            raw_score = review_score + trace_score + claim_score
            credibility_score = round(min(score_ceiling, raw_score), 1)
            # Claim has no partial score. A resource without a fully passed
            # Claim audit remains capped at 80; a fully passed Claim audit
            # raises the ceiling to 99 without presenting absolute certainty.
            ceiling_applied = not claim_passed
            hard_failure = blocking or cross_knowledge_base
            credibility_level = (
                "attention" if hard_failure else "high" if credibility_score >= 90.0
                else "good" if credibility_score >= 80.0 else "moderate" if credibility_score >= 60.0
                else "low" if credibility_score > 0 else "insufficient_evidence"
            )
            score_reason_codes = []
            if review_score_status == "passed_with_issues": score_reason_codes.append("PUBLICATION_REVIEW_NON_BLOCKING_ISSUES")
            elif review_score_status == "not_measured": score_reason_codes.append("PUBLICATION_REVIEW_NOT_MEASURED")
            elif review_score_status == "failed": score_reason_codes.append("PUBLICATION_REVIEW_FAILED")
            if cross_knowledge_base: score_reason_codes.append("SOURCE_REF_CROSS_KNOWLEDGE_BASE")
            elif not refs: score_reason_codes.append("SOURCE_REF_MISSING")
            elif len(verified) < len(refs): score_reason_codes.append("SOURCE_REF_PARTIALLY_VERIFIED")
            if claim_status == "not_measured": score_reason_codes.append("CLAIM_REVIEW_NOT_MEASURED")
            elif claim_status == "not_applicable": score_reason_codes.append("CLAIM_REVIEW_NOT_APPLICABLE")
            elif claim_status == "failed": score_reason_codes.append("CLAIM_REVIEW_FAILED")
            required = [review_status, claim_status, trace_status]
            grade = "attention" if "failed" in required else "trusted" if review_status == "passed" and claim_status in {"passed", "not_applicable"} and trace_status == "passed" else "insufficient_evidence"
            items.append({"schema_version": "1.0", "resource_id": resource.resource_id, "resource_type": resource.resource_type,
                          "topic": resource.topic, "run_id": resource.run_id, "batch_id": resource.batch_id,
                          "resource_version": resource.version, "published_at": resource.published_at, "grade": grade,
                           "publication_review": {"status": review_status, "publication_status": resource.publication_status, "review_status": review_status_value, "review_id": resource.review_id, "blocking_issue_count": blocking_count, "issue_count": len(issues), "score_status": review_score_status},
                          "claim_support": {"status": claim_status, "metric_status": metric, "unsupported_rate": unsupported_rate, **claim_counts},
                          "source_traceability": {"status": trace_status, "source_ref_count": len(refs), "verified_source_ref_count": len(verified), "evidence_bound_count": len(verified), "unique_document_count": len({ref.doc_id for ref in verified})},
                          "source_authority": {"status": "not_measured", "reason_code": "SOURCE_AUTHORITY_NOT_MEASURED"},
                           "difficulty_fit": {"status": "measured" if resource.difficulty_match is not None else "not_measured", "value": resource.difficulty_match},
                           "credibility_score": credibility_score, "credibility_level": credibility_level,
                           "score_breakdown": {"publication_review_score": review_score, "source_traceability_score": trace_score,
                                               "claim_review_score": claim_score, "claim_review_passed": claim_passed,
                                               "score_ceiling": score_ceiling, "ceiling_applied": ceiling_applied,
                                               "reason_codes": list(dict.fromkeys(score_reason_codes))},
                           # Keep this legacy field stable for existing report consumers.
                           "reason_codes": ["SOURCE_REF_CROSS_KNOWLEDGE_BASE"] if cross_knowledge_base else []})
        items.sort(key=lambda item: (-self._utc(item["published_at"] or datetime.min.replace(tzinfo=timezone.utc)).timestamp(), item["resource_id"]))
        total = len(items); trusted = sum(item["grade"] == "trusted" for item in items); attention = sum(item["grade"] == "attention" for item in items)
        fully = sum(item["grade"] != "insufficient_evidence" for item in items)
        scores = [item["credibility_score"] for item in items if item.get("credibility_score") is not None]
        level_counts = {level: sum(item["credibility_level"] == level for item in items) for level in ("attention", "high", "good", "moderate", "low", "insufficient_evidence")}
        return {"items": items, "summary": {"total_count": total, "trusted_count": trusted, "attention_count": attention,
                "insufficient_evidence_count": total - trusted - attention, "fully_measured_count": fully,
                "measurement_coverage": fully / total if total else None, "scored_count": len(scores),
                "average_credibility_score": round(sum(scores) / len(scores), 1) if scores else None,
                "claim_review_passed_count": sum(item["score_breakdown"]["claim_review_passed"] for item in items),
                "claim_ceiling_applied_count": sum(item["score_breakdown"]["ceiling_applied"] for item in items),
                "scoring_strategy_version": "audit-40/source-50/claim-10/v1",
                **{f"credibility_{level}_count": count for level, count in level_counts.items()},
                "notice": "可信等级表示平台可验证的生成质量证据，不等价于来源机构权威性或绝对事实正确。"}}

    def _claims_for_resource(self, resource):
        if not self.claim_repo or not resource.run_id or not resource.review_id:
            return [], []
        claims = [item for item in self.claim_repo.list_claims_by_run(resource.run_id)
                  if item.resource_id == resource.resource_id and item.resource_version == resource.version and item.review_id == resource.review_id]
        claim_ids = {item.claim_id for item in claims}
        judgements = [item for item in self.claim_repo.list_judgements_by_run(resource.run_id)
                      if item.claim_id in claim_ids and item.resource_id == resource.resource_id and item.resource_version == resource.version and item.review_id == resource.review_id]
        return claims, judgements

    def _visible_resources(self, learner_id: str):
        """Return the learner-facing projection, excluding superseded versions."""
        resources = self.resource_repo.list_by_learner(learner_id)
        published_parent_ids = {
            resource.parent_resource_id for resource in resources
            if resource.publication_status == "published" and resource.parent_resource_id
        }
        if self.generation_job_repo is None:
            return [resource for resource in resources if resource.resource_id not in published_parent_ids]

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
            and resource.resource_id not in published_parent_ids
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
