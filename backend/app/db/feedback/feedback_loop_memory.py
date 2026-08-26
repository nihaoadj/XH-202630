from __future__ import annotations

from threading import RLock

from app.db.feedback.feedback_loop_base import (
    BaseFeedbackLoopRepository,
    FeedbackIdempotencyConflict,
    LearnerProfileVersionConflict,
    LearningPathMutationConflict,
)
from app.db.learners.base import BaseLearnerRepository
from app.db.learners.mastery import MemoryMasteryRepository
from app.models.learners.mastery import AbilityEvidenceV1
from app.models.feedback.feedback_loop import (
    FeedbackContext,
    FeedbackDecision,
    FeedbackLoopResult,
    FollowUpGenerationStatus,
    KnowledgeStateMutation,
    KnowledgeStateValue,
    LearningAttempt,
    LearningPath,
    PathMutation,
    ProfileVersionRecord,
)
from app.models.learning_documents.schemas import KnowledgeState


def _assessment_metadata(attempt: LearningAttempt, point_id: str) -> dict:
    metadata = attempt.metadata or {}
    traces = [
        item for item in metadata.get("question_trace", [])
        if isinstance(item, dict)
        and str(item.get("skill_node_id") or item.get("knowledge_point") or "") == point_id
    ]
    audit = str((metadata.get("scoring_audit") or {}).get(point_id, "single_pass"))
    return {
        "assessment_kind": metadata.get("assessment_kind", "learning_check"),
        "assessment_session_id": metadata.get("assessment_session_id") or attempt.attempt_id,
        "assessment_form_id": metadata.get("assessment_form_id") or attempt.source_resource_id,
        "question_ids": [str(item.get("question_id")) for item in traces if item.get("question_id")],
        "covered_dimensions": list(dict.fromkeys(
            str(item.get("diagnostic_dimension")) for item in traces
            if item.get("diagnostic_dimension") in {"concept", "scenario", "misconception", "practice"}
        )),
        "scoring_audit_status": audit,
        "evidence_eligible": audit not in {"double_disagreement", "failed"},
    }


class MemoryFeedbackLoopRepository(BaseFeedbackLoopRepository):
    def __init__(
        self,
        learner_repository: BaseLearnerRepository,
        mastery_repository: MemoryMasteryRepository | None = None,
    ):
        self.learner_repository = learner_repository
        self._attempts: dict[str, LearningAttempt] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._decisions: dict[str, FeedbackDecision] = {}
        self._state_mutations: dict[str, list[KnowledgeStateMutation]] = {}
        self._paths: dict[str, LearningPath] = {}
        self._path_mutations: dict[str, PathMutation] = {}
        self._versions: dict[str, list[ProfileVersionRecord]] = {}
        self._followups: dict[str, dict] = {}
        self._state_values: dict[tuple[str, str], KnowledgeStateValue] = {}
        self._lock = RLock()
        self.mastery_repository = mastery_repository
        self.stores_mastery_evidence_atomically = mastery_repository is not None

    def get_context(self, learner_id: str, knowledge_point_ids: list[str]) -> FeedbackContext:
        profile = self.learner_repository.get(learner_id)
        if profile is None:
            raise ValueError("learner profile not found")
        states = {
            point_id: self._state_values[(learner_id, point_id)].model_copy(deep=True)
            for point_id in knowledge_point_ids
            if (learner_id, point_id) in self._state_values
        }
        for point_id in knowledge_point_ids:
            if point_id in states:
                continue
            cached = profile.knowledge_states.get(point_id)
            if cached is not None:
                states[point_id] = KnowledgeStateValue(
                    mastery=cached.score,
                    status=cached.status or "unassessed",
                    self_report_prior=cached.self_report_prior,
                    confidence=cached.confidence or "none",
                    objective_evidence_count=cached.objective_evidence_count,
                    distinct_objective_source_count=cached.distinct_objective_source_count,
                    attempt_count=cached.attempt_count,
                    last_evidence_type=cached.last_evidence_type,
                    last_evidence_id=cached.last_evidence_id,
                    last_attempt_id=cached.last_evidence_id if cached.last_evidence_type == "learning_attempt" else None,
                    row_version=cached.row_version,
                )
        recent: dict[str, list[float]] = {}
        for point_id in knowledge_point_ids:
            values = [
                item.score or 0.0
                for attempt in reversed(list(self._attempts.values()))
                if attempt.learner_id == learner_id
                for item in attempt.knowledge_point_results
                if item.knowledge_point_id == point_id
            ][:5]
            recent[point_id] = values
        return FeedbackContext(
            learner_id=learner_id,
            profile_version=profile.profile_version,
            knowledge_states=states,
            recent_point_scores=recent,
            learning_path=self.get_current_path(learner_id),
        )

    def get_by_idempotency_key(self, learner_id: str, idempotency_key: str) -> FeedbackLoopResult | None:
        attempt_id = self._idempotency.get((learner_id, idempotency_key))
        return self._result(attempt_id, replay=True) if attempt_id else None

    def apply_feedback(
        self,
        *,
        attempt: LearningAttempt,
        decision: FeedbackDecision,
        state_mutations: list[KnowledgeStateMutation],
        learning_path: LearningPath,
        path_mutation: PathMutation,
        profile_version: ProfileVersionRecord,
        profile_patch: dict,
    ) -> FeedbackLoopResult:
        with self._lock:
            key = (attempt.learner_id, attempt.idempotency_key)
            existing_id = self._idempotency.get(key)
            if existing_id:
                existing = self._attempts[existing_id]
                if existing.request_hash != attempt.request_hash:
                    raise FeedbackIdempotencyConflict("idempotency key payload conflict")
                return self._result(existing_id, replay=True)
            profile = self.learner_repository.get(attempt.learner_id)
            if profile is None:
                raise ValueError("learner profile not found")
            if profile.profile_version != attempt.expected_profile_version:
                raise LearnerProfileVersionConflict("stale learner profile version")
            current_path = self._paths.get(attempt.learner_id)
            if current_path and current_path.version != path_mutation.path_version_before:
                raise LearningPathMutationConflict("stale learning path version")

            self._attempts[attempt.attempt_id] = attempt.model_copy(deep=True)
            self._idempotency[key] = attempt.attempt_id
            self._decisions[attempt.attempt_id] = decision.model_copy(deep=True)
            self._state_mutations[attempt.attempt_id] = [item.model_copy(deep=True) for item in state_mutations]
            for item in state_mutations:
                self._state_values[(attempt.learner_id, item.knowledge_point_id)] = item.after.model_copy(deep=True)
                profile.knowledge_states[item.knowledge_point_id] = KnowledgeState(
                    score=item.after.mastery,
                    status=item.after.status,
                    evidence=[attempt.attempt_id],
                    self_report_prior=item.after.self_report_prior,
                    confidence=item.after.confidence,
                    objective_evidence_count=item.after.objective_evidence_count,
                    distinct_objective_source_count=item.after.distinct_objective_source_count,
                    attempt_count=item.after.attempt_count,
                    last_evidence_type="learning_attempt",
                    last_evidence_id=attempt.attempt_id,
                    row_version=item.after.row_version,
                )
                profile.theory_scores[item.knowledge_point_id] = round(float(item.after.mastery or 0.0) * 100, 1)
            profile.profile_version = profile_version.profile_version
            profile.skill_level = profile_patch["skill_level"]
            profile.weak_points = list(profile_patch["weak_points"])
            profile.strong_points = list(profile_patch["strong_points"])
            profile.last_feedback_summary = dict(profile_patch["last_feedback_summary"])
            self.learner_repository.save(profile.model_copy(deep=True))
            if self.mastery_repository is not None and profile.knowledge_base_id:
                self.mastery_repository.apply_evidence(
                    [AbilityEvidenceV1(
                        evidence_id=f"abe_{attempt.attempt_id}_{item.knowledge_point_id}",
                        learner_id=attempt.learner_id,
                        knowledge_base_id=profile.knowledge_base_id,
                        skill_node_id=item.knowledge_point_id,
                        source_type="learning_attempt",
                        source_id=attempt.attempt_id,
                        source_hash=attempt.request_hash,
                        observed_score=next(
                            value.score for value in attempt.knowledge_point_results
                            if value.knowledge_point_id == item.knowledge_point_id
                        ),
                        verified=True,
                        **_assessment_metadata(attempt, item.knowledge_point_id),
                        occurred_at=attempt.submitted_at,
                    ) for item in state_mutations],
                    {item.knowledge_point_id: item.knowledge_point_id for item in state_mutations},
                    increment_profile_version=False,
                )
            self._paths[attempt.learner_id] = learning_path.model_copy(deep=True)
            self._path_mutations[attempt.attempt_id] = path_mutation.model_copy(deep=True)
            self._versions.setdefault(attempt.learner_id, []).append(profile_version.model_copy(deep=True))
            return self._result(attempt.attempt_id, replay=False)

    def attach_followup(
        self,
        *,
        attempt_id: str,
        decision_id: str,
        parent_run_id: str | None,
        child_run_id: str | None,
        trigger_type: str,
        status: str,
        error_code: str | None = None,
    ) -> FeedbackLoopResult:
        with self._lock:
            existing = self._followups.get(attempt_id)
            payload = {
                "decision_id": decision_id,
                "parent_run_id": parent_run_id,
                "child_run_id": child_run_id,
                "trigger_type": trigger_type,
                "status": status,
                "error_code": error_code,
            }
            if existing and existing != payload:
                retrying_failed_relation = (
                    existing.get("decision_id") == decision_id
                    and existing.get("parent_run_id") == parent_run_id
                    and existing.get("trigger_type") == trigger_type
                    and existing.get("status") == "failed"
                    and status == "queued"
                )
                if not retrying_failed_relation:
                    raise FeedbackIdempotencyConflict("attempt already has another follow-up")
            self._followups[attempt_id] = payload
            return self._result(attempt_id, replay=False)

    def list_attempts(self, learner_id: str, limit: int = 20) -> list[LearningAttempt]:
        items = [item.model_copy(deep=True) for item in self._attempts.values() if item.learner_id == learner_id]
        return sorted(items, key=lambda item: item.submitted_at, reverse=True)[:limit]

    def list_results(self, learner_id: str, limit: int = 20) -> list[FeedbackLoopResult]:
        attempts = self.list_attempts(learner_id, limit)
        return [self._result(item.attempt_id, replay=False) for item in attempts]

    def get_current_path(self, learner_id: str) -> LearningPath | None:
        item = self._paths.get(learner_id)
        return item.model_copy(deep=True) if item else None

    def list_profile_versions(self, learner_id: str, limit: int = 20) -> list[ProfileVersionRecord]:
        return [item.model_copy(deep=True) for item in reversed(self._versions.get(learner_id, []))][:limit]

    def get_followup_relation(self, child_run_id: str) -> dict | None:
        for attempt_id, item in self._followups.items():
            if item.get("child_run_id") == child_run_id:
                return {"attempt_id": attempt_id, **item}
        return None

    def reconcile_incomplete_followups(
        self,
        *,
        stale_child_run_ids: list[str],
        error_code: str,
    ) -> int:
        stale = set(stale_child_run_ids)
        reconciled = 0
        with self._lock:
            for attempt_id, decision in self._decisions.items():
                if decision.action.value not in {"remediate", "advance"}:
                    continue
                attempt = self._attempts[attempt_id]
                relation = self._followups.get(attempt_id)
                if relation and relation.get("child_run_id") in stale and relation.get("status") == "queued":
                    relation["status"] = "failed"
                    relation["error_code"] = error_code
                    reconciled += 1
        return reconciled

    def _result(self, attempt_id: str, *, replay: bool) -> FeedbackLoopResult:
        attempt = self._attempts[attempt_id]
        followup = self._followups.get(attempt_id, {})
        status = FollowUpGenerationStatus(followup.get("status", "not_requested"))
        return FeedbackLoopResult(
            attempt=attempt.model_copy(deep=True),
            decision=self._decisions[attempt_id].model_copy(deep=True),
            profile_version=self._versions[attempt.learner_id][-1].profile_version
            if not replay
            else next(
                item.profile_version
                for item in self._versions[attempt.learner_id]
                if item.source_attempt_id == attempt_id
            ),
            knowledge_state_updates=[item.model_copy(deep=True) for item in self._state_mutations[attempt_id]],
            learning_path=self._paths[attempt.learner_id].model_copy(deep=True),
            path_mutation=self._path_mutations[attempt_id].model_copy(deep=True),
            followup_generation_status=status,
            followup_run_id=followup.get("child_run_id"),
            followup_job_id=followup.get("child_run_id"),
            followup_error_code=followup.get("error_code"),
            idempotent_replay=replay,
        )
