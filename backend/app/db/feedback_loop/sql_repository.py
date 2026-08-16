from __future__ import annotations

import hashlib
from collections.abc import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.feedback_loop.base import (
    BaseFeedbackLoopRepository,
    FeedbackIdempotencyConflict,
    LearnerProfileVersionConflict,
    LearningPathMutationConflict,
)
from app.db.models import (
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    KnowledgeStateMutationORM,
    KnowledgeStateORM,
    LearnerProfileORM,
    LearnerProfileVersionORM,
    LearningAttemptORM,
    LearningAttemptPointResultORM,
    LearningPathMutationORM,
    LearningPathNodeORM,
    LearningPathORM,
)
from app.models.feedback_loop import (
    FeedbackContext,
    FeedbackDecision,
    FeedbackLoopResult,
    FollowUpGenerationStatus,
    KnowledgePointAttemptResult,
    KnowledgeStateMutation,
    KnowledgeStateValue,
    LearningAttempt,
    LearningPath,
    LearningPathNode,
    PathMutation,
    ProfileVersionRecord,
)


def _stable_id(prefix: str, *parts: object) -> str:
    value = "\x1f".join(str(part) for part in parts)
    return f"{prefix}_{hashlib.sha256(value.encode()).hexdigest()[:32]}"


class SQLFeedbackLoopRepository(BaseFeedbackLoopRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get_context(self, learner_id: str, knowledge_point_ids: list[str]) -> FeedbackContext:
        with self.session_factory() as db:
            profile = db.get(LearnerProfileORM, learner_id)
            if profile is None:
                raise ValueError("learner profile not found")
            rows = db.query(KnowledgeStateORM).filter(
                KnowledgeStateORM.learner_id == learner_id,
                KnowledgeStateORM.skill_node_id.in_(knowledge_point_ids or {""}),
            ).all()
            states = {
                row.skill_node_id: KnowledgeStateValue(
                    mastery=row.mastery_score or 0.0,
                    status=row.status or "weak",
                    attempt_count=row.attempt_count or 0,
                    last_attempt_id=row.last_attempt_id,
                    row_version=row.row_version or 0,
                )
                for row in rows
            }
            recent: dict[str, list[float]] = {}
            for point_id in knowledge_point_ids:
                score_rows = (
                    db.query(LearningAttemptPointResultORM.score)
                    .join(LearningAttemptORM, LearningAttemptORM.attempt_id == LearningAttemptPointResultORM.attempt_id)
                    .filter(
                        LearningAttemptORM.learner_id == learner_id,
                        LearningAttemptPointResultORM.knowledge_point_id == point_id,
                    )
                    .order_by(LearningAttemptORM.submitted_at.desc())
                    .limit(5)
                    .all()
                )
                recent[point_id] = [float(row[0]) for row in score_rows]
            return FeedbackContext(
                learner_id=learner_id,
                profile_version=profile.profile_version or 1,
                knowledge_states=states,
                recent_point_scores=recent,
                learning_path=self._load_path(db, learner_id),
            )

    def get_by_idempotency_key(self, learner_id: str, idempotency_key: str) -> FeedbackLoopResult | None:
        with self.session_factory() as db:
            attempt = db.query(LearningAttemptORM).filter_by(
                learner_id=learner_id,
                idempotency_key=idempotency_key,
            ).first()
            return self._load_result(db, attempt.attempt_id, replay=True) if attempt else None

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
        try:
            with self.session_factory() as db:
                existing = db.query(LearningAttemptORM).filter_by(
                    learner_id=attempt.learner_id,
                    idempotency_key=attempt.idempotency_key,
                ).first()
                if existing:
                    if existing.request_hash != attempt.request_hash:
                        raise FeedbackIdempotencyConflict("idempotency key payload conflict")
                    return self._load_result(db, existing.attempt_id, replay=True)
                profile = (
                    db.query(LearnerProfileORM)
                    .filter_by(learner_id=attempt.learner_id)
                    .with_for_update()
                    .first()
                )
                if profile is None:
                    raise ValueError("learner profile not found")
                if (profile.profile_version or 1) != attempt.expected_profile_version:
                    raise LearnerProfileVersionConflict("stale learner profile version")
                stored_path = (
                    db.query(LearningPathORM)
                    .filter_by(learner_id=attempt.learner_id)
                    .with_for_update()
                    .first()
                )
                if stored_path and stored_path.version != path_mutation.path_version_before:
                    raise LearningPathMutationConflict("stale learning path version")

                db.add(LearningAttemptORM(
                    attempt_id=attempt.attempt_id,
                    schema_version=attempt.schema_version,
                    learner_id=attempt.learner_id,
                    source_resource_id=attempt.source_resource_id,
                    source_resource_version=attempt.source_resource_version,
                    source_run_id=attempt.source_run_id,
                    path_node_id=attempt.path_node_id,
                    idempotency_key=attempt.idempotency_key,
                    request_hash=attempt.request_hash,
                    expected_profile_version=attempt.expected_profile_version,
                    overall_score=attempt.overall_score,
                    duration_ms=attempt.duration_ms,
                    hint_count=attempt.hint_count,
                    extra_metadata=attempt.metadata,
                    started_at=attempt.started_at,
                    submitted_at=attempt.submitted_at,
                    created_at=attempt.created_at,
                ))
                for item in attempt.knowledge_point_results:
                    db.add(LearningAttemptPointResultORM(
                        result_id=_stable_id("apr", attempt.attempt_id, item.knowledge_point_id),
                        attempt_id=attempt.attempt_id,
                        knowledge_point_id=item.knowledge_point_id,
                        question_ids=item.question_ids,
                        correct_count=item.correct_count,
                        total_count=item.total_count,
                        score=item.score,
                        duration_ms=item.duration_ms,
                        hint_count=item.hint_count,
                    ))
                db.add(FeedbackDecisionORM(
                    decision_id=decision.decision_id,
                    learner_id=decision.learner_id,
                    attempt_id=decision.attempt_id,
                    action=decision.action.value,
                    reason_codes=decision.reason_codes,
                    decision_reason=decision.decision_reason,
                    target_knowledge_point_ids=decision.target_knowledge_point_ids,
                    decision_hash=decision.decision_hash,
                    created_at=decision.created_at,
                ))
                profile_states = dict(profile.knowledge_states or {})
                if not profile.knowledge_base_id:
                    raise ValueError("learner knowledge_base_id is required for mastery updates")
                for item in state_mutations:
                    row = db.query(KnowledgeStateORM).filter_by(
                        learner_id=attempt.learner_id,
                        knowledge_base_id=profile.knowledge_base_id,
                        skill_node_id=item.knowledge_point_id,
                    ).with_for_update().first()
                    if row is None:
                        if item.before is not None:
                            raise LearnerProfileVersionConflict("knowledge state disappeared")
                        row = KnowledgeStateORM(
                            state_id=_stable_id("kst", attempt.learner_id, profile.knowledge_base_id, item.knowledge_point_id),
                            learner_id=attempt.learner_id,
                            knowledge_base_id=profile.knowledge_base_id,
                            skill_node_id=item.knowledge_point_id,
                        )
                        db.add(row)
                    elif item.before is None or (row.row_version or 0) != item.before.row_version:
                        raise LearnerProfileVersionConflict("knowledge state version conflict")
                    row.mastery_score = item.after.mastery
                    row.status = item.after.status
                    row.evidence = list(dict.fromkeys([*(row.evidence or []), attempt.attempt_id]))[-20:]
                    row.attempt_count = item.after.attempt_count
                    row.last_attempt_id = attempt.attempt_id
                    row.row_version = item.after.row_version
                    profile_states[item.knowledge_point_id] = {
                        "score": item.after.mastery,
                        "status": item.after.status,
                        "evidence": [attempt.attempt_id],
                    }
                    db.add(KnowledgeStateMutationORM(
                        mutation_id=_stable_id("ksm", attempt.attempt_id, item.knowledge_point_id),
                        learner_id=attempt.learner_id,
                        knowledge_point_id=item.knowledge_point_id,
                        attempt_id=attempt.attempt_id,
                        before_state=item.before.model_dump(mode="json") if item.before else None,
                        after_state=item.after.model_dump(mode="json"),
                        reason=item.reason,
                    ))

                if stored_path is None:
                    stored_path = LearningPathORM(
                        path_id=learning_path.path_id,
                        learner_id=learning_path.learner_id,
                        version=learning_path.version,
                        status=learning_path.status,
                        created_at=learning_path.created_at,
                        updated_at=learning_path.updated_at,
                    )
                    db.add(stored_path)
                else:
                    stored_path.version = learning_path.version
                    stored_path.status = learning_path.status
                    stored_path.updated_at = learning_path.updated_at
                for node in learning_path.nodes:
                    row = db.get(LearningPathNodeORM, node.node_id)
                    if row is None:
                        db.add(LearningPathNodeORM(
                            node_id=node.node_id,
                            path_id=node.path_id,
                            knowledge_point_id=node.knowledge_point_id,
                            node_type=node.node_type.value,
                            sequence=node.sequence,
                            status=node.status.value,
                            prerequisite_ids=node.prerequisite_ids,
                            parent_node_id=node.parent_node_id,
                            source=node.source,
                            difficulty=node.difficulty,
                            created_at=node.created_at,
                            updated_at=node.updated_at,
                        ))
                    else:
                        row.status = node.status.value
                        row.updated_at = node.updated_at
                db.add(LearningPathMutationORM(
                    mutation_id=path_mutation.mutation_id,
                    learner_id=path_mutation.learner_id,
                    path_id=path_mutation.path_id,
                    attempt_id=path_mutation.attempt_id,
                    decision_id=path_mutation.decision_id,
                    mutation_type=path_mutation.mutation_type.value,
                    target_node_id=path_mutation.target_node_id,
                    inserted_node_ids=path_mutation.inserted_node_ids,
                    unlocked_node_ids=path_mutation.unlocked_node_ids,
                    completed_node_ids=path_mutation.completed_node_ids,
                    reason_codes=path_mutation.reason_codes,
                    path_version_before=path_mutation.path_version_before,
                    path_version_after=path_mutation.path_version_after,
                    created_at=path_mutation.created_at,
                ))
                db.add(LearnerProfileVersionORM(
                    version_id=_stable_id("pfv", profile_version.learner_id, profile_version.profile_version),
                    learner_id=profile_version.learner_id,
                    profile_version=profile_version.profile_version,
                    source_attempt_id=profile_version.source_attempt_id,
                    source_decision_id=profile_version.source_decision_id,
                    change_summary=profile_version.change_summary,
                    created_at=profile_version.created_at,
                ))
                profile.knowledge_states = profile_states
                profile.profile_version = profile_version.profile_version
                profile.skill_level = profile_patch["skill_level"]
                profile.weak_points = profile_patch["weak_points"]
                profile.strong_points = profile_patch["strong_points"]
                profile.last_feedback_summary = profile_patch["last_feedback_summary"]
                db.commit()
                return self._load_result(db, attempt.attempt_id, replay=False)
        except IntegrityError as exc:
            existing = self.get_by_idempotency_key(attempt.learner_id, attempt.idempotency_key)
            if existing and existing.attempt.request_hash == attempt.request_hash:
                return existing
            with self.session_factory() as check_db:
                profile = check_db.get(LearnerProfileORM, attempt.learner_id)
                if profile is not None and (profile.profile_version or 1) != attempt.expected_profile_version:
                    raise LearnerProfileVersionConflict("concurrent learner profile update") from exc
            if existing:
                raise FeedbackIdempotencyConflict("feedback transaction uniqueness conflict") from exc
            raise LearningPathMutationConflict("concurrent learning path mutation") from exc

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
        with self.session_factory() as db:
            row = db.query(FeedbackFollowUpRunORM).filter_by(attempt_id=attempt_id).first()
            if row:
                if row.child_run_id != child_run_id or row.status != status:
                    retrying_failed_relation = (
                        row.decision_id == decision_id
                        and row.parent_run_id == parent_run_id
                        and row.trigger_type == trigger_type
                        and row.status == "failed"
                        and status == "queued"
                    )
                    if not retrying_failed_relation:
                        raise FeedbackIdempotencyConflict("attempt already has another follow-up")
                    row.child_run_id = child_run_id
                    row.status = status
                    row.error_code = error_code
                    db.commit()
            else:
                db.add(FeedbackFollowUpRunORM(
                    relation_id=_stable_id("fur", attempt_id),
                    attempt_id=attempt_id,
                    decision_id=decision_id,
                    parent_run_id=parent_run_id,
                    child_run_id=child_run_id,
                    trigger_type=trigger_type,
                    status=status,
                    error_code=error_code,
                ))
                db.commit()
            return self._load_result(db, attempt_id, replay=False)

    def list_attempts(self, learner_id: str, limit: int = 20) -> list[LearningAttempt]:
        with self.session_factory() as db:
            rows = db.query(LearningAttemptORM).filter_by(learner_id=learner_id).order_by(
                LearningAttemptORM.submitted_at.desc()
            ).limit(limit).all()
            return [self._load_attempt(db, row) for row in rows]

    def list_results(self, learner_id: str, limit: int = 20) -> list[FeedbackLoopResult]:
        with self.session_factory() as db:
            rows = db.query(LearningAttemptORM.attempt_id).filter_by(learner_id=learner_id).order_by(
                LearningAttemptORM.submitted_at.desc()
            ).limit(limit).all()
            return [self._load_result(db, row[0], replay=False) for row in rows]

    def get_current_path(self, learner_id: str) -> LearningPath | None:
        with self.session_factory() as db:
            return self._load_path(db, learner_id)

    def list_profile_versions(self, learner_id: str, limit: int = 20) -> list[ProfileVersionRecord]:
        with self.session_factory() as db:
            rows = db.query(LearnerProfileVersionORM).filter_by(learner_id=learner_id).order_by(
                LearnerProfileVersionORM.profile_version.desc()
            ).limit(limit).all()
            return [ProfileVersionRecord(
                learner_id=row.learner_id,
                profile_version=row.profile_version,
                source_attempt_id=row.source_attempt_id,
                source_decision_id=row.source_decision_id,
                change_summary=row.change_summary or {},
                created_at=row.created_at,
            ) for row in rows]

    def get_followup_relation(self, child_run_id: str) -> dict | None:
        with self.session_factory() as db:
            row = db.query(FeedbackFollowUpRunORM).filter_by(child_run_id=child_run_id).first()
            if row is None:
                return None
            return {
                "attempt_id": row.attempt_id,
                "decision_id": row.decision_id,
                "parent_run_id": row.parent_run_id,
                "child_run_id": row.child_run_id,
                "trigger_type": row.trigger_type,
                "status": row.status,
                "error_code": row.error_code,
            }

    def _load_attempt(self, db: Session, row: LearningAttemptORM) -> LearningAttempt:
        points = db.query(LearningAttemptPointResultORM).filter_by(attempt_id=row.attempt_id).order_by(
            LearningAttemptPointResultORM.knowledge_point_id
        ).all()
        return LearningAttempt(
            attempt_id=row.attempt_id,
            request_hash=row.request_hash,
            learner_id=row.learner_id,
            source_resource_id=row.source_resource_id,
            source_resource_version=row.source_resource_version,
            source_run_id=row.source_run_id,
            path_node_id=row.path_node_id,
            idempotency_key=row.idempotency_key,
            expected_profile_version=row.expected_profile_version,
            started_at=row.started_at,
            submitted_at=row.submitted_at,
            duration_ms=row.duration_ms,
            hint_count=row.hint_count,
            overall_score=row.overall_score,
            knowledge_point_results=[KnowledgePointAttemptResult(
                knowledge_point_id=item.knowledge_point_id,
                question_ids=item.question_ids or [],
                correct_count=item.correct_count,
                total_count=item.total_count,
                score=item.score,
                duration_ms=item.duration_ms,
                hint_count=item.hint_count,
            ) for item in points],
            metadata=row.extra_metadata or {},
            created_at=row.created_at,
        )

    def _load_path(self, db: Session, learner_id: str) -> LearningPath | None:
        row = db.query(LearningPathORM).filter_by(learner_id=learner_id).first()
        if row is None:
            return None
        nodes = db.query(LearningPathNodeORM).filter_by(path_id=row.path_id).order_by(
            LearningPathNodeORM.sequence, LearningPathNodeORM.node_id
        ).all()
        return LearningPath(
            path_id=row.path_id,
            learner_id=row.learner_id,
            version=row.version,
            status=row.status,
            nodes=[LearningPathNode(
                node_id=item.node_id,
                path_id=item.path_id,
                knowledge_point_id=item.knowledge_point_id,
                node_type=item.node_type,
                sequence=item.sequence,
                status=item.status,
                prerequisite_ids=item.prerequisite_ids or [],
                parent_node_id=item.parent_node_id,
                source=item.source,
                difficulty=item.difficulty,
                created_at=item.created_at,
                updated_at=item.updated_at,
            ) for item in nodes],
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _load_result(self, db: Session, attempt_id: str, *, replay: bool) -> FeedbackLoopResult:
        attempt_row = db.get(LearningAttemptORM, attempt_id)
        if attempt_row is None:
            raise ValueError("attempt not found")
        attempt = self._load_attempt(db, attempt_row)
        decision_row = db.query(FeedbackDecisionORM).filter_by(attempt_id=attempt_id).one()
        decision = FeedbackDecision(
            decision_id=decision_row.decision_id,
            learner_id=decision_row.learner_id,
            attempt_id=decision_row.attempt_id,
            action=decision_row.action,
            reason_codes=decision_row.reason_codes or [],
            decision_reason=decision_row.decision_reason,
            target_knowledge_point_ids=decision_row.target_knowledge_point_ids or [],
            decision_hash=decision_row.decision_hash,
            created_at=decision_row.created_at,
        )
        mutation_rows = db.query(KnowledgeStateMutationORM).filter_by(attempt_id=attempt_id).order_by(
            KnowledgeStateMutationORM.knowledge_point_id
        ).all()
        mutations = [KnowledgeStateMutation(
            knowledge_point_id=item.knowledge_point_id,
            before=KnowledgeStateValue.model_validate(item.before_state) if item.before_state else None,
            after=KnowledgeStateValue.model_validate(item.after_state),
            source_attempt_id=item.attempt_id,
            reason=item.reason,
        ) for item in mutation_rows]
        path_mutation_row = db.query(LearningPathMutationORM).filter_by(attempt_id=attempt_id).one()
        path_mutation = PathMutation(
            mutation_id=path_mutation_row.mutation_id,
            learner_id=path_mutation_row.learner_id,
            path_id=path_mutation_row.path_id,
            attempt_id=path_mutation_row.attempt_id,
            decision_id=path_mutation_row.decision_id,
            mutation_type=path_mutation_row.mutation_type,
            target_node_id=path_mutation_row.target_node_id,
            inserted_node_ids=path_mutation_row.inserted_node_ids or [],
            unlocked_node_ids=path_mutation_row.unlocked_node_ids or [],
            completed_node_ids=path_mutation_row.completed_node_ids or [],
            reason_codes=path_mutation_row.reason_codes or [],
            path_version_before=path_mutation_row.path_version_before,
            path_version_after=path_mutation_row.path_version_after,
            created_at=path_mutation_row.created_at,
        )
        version = db.query(LearnerProfileVersionORM).filter_by(source_attempt_id=attempt_id).one()
        followup = db.query(FeedbackFollowUpRunORM).filter_by(attempt_id=attempt_id).first()
        return FeedbackLoopResult(
            attempt=attempt,
            decision=decision,
            profile_version=version.profile_version,
            knowledge_state_updates=mutations,
            learning_path=self._load_path(db, attempt.learner_id),
            path_mutation=path_mutation,
            followup_generation_status=FollowUpGenerationStatus(followup.status) if followup else FollowUpGenerationStatus.NOT_REQUESTED,
            followup_run_id=followup.child_run_id if followup else None,
            followup_job_id=followup.child_run_id if followup else None,
            followup_error_code=followup.error_code if followup else None,
            idempotent_replay=replay,
        )
