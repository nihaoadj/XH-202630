"""SQLAlchemy implementation of the learner-profile repository."""
import logging
from typing import Callable, Dict, Optional

from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from app.core.storage.file_storage import stage_learner_resource_directories
from app.db.shared.extended_models import DiagnosticRunORM
from app.db.learners.base import BaseLearnerRepository
from app.db.shared.models import (
    AgentRunORM,
    AgentStepORM,
    ClaimEvidenceORM,
    ClaimJudgementORM,
    ContestEvalResultORM,
    DiagnosticAnswerORM,
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    FeedbackRecordORM,
    GeneratedResourceORM,
    GenerationJobORM,
    KnowledgeStateMutationORM,
    KnowledgeStateORM,
    LearnerProfileORM,
    LearnerProfileVersionORM,
    LearningAttemptORM,
    LearningAttemptPointResultORM,
    LearningPathMutationORM,
    LearningPathNodeORM,
    LearningPathORM,
    QuestionnaireAnswerORM,
    QuestionnaireSubmissionORM,
    ResourceClaimORM,
    ResourceExecutionORM,
    ResourceReviewORM,
    ResourceSpecORM,
    RetrievalEvidenceSnapshotORM,
    WorkflowCheckpointORM,
    WorkflowEventORM,
)
from app.models.learning_documents.schemas import KnowledgeState, LearnerProfile, LearningPreferences


logger = logging.getLogger(__name__)


def _ids(rows) -> set[str]:
    """Extract non-null scalar identifiers from SQLAlchemy result rows."""
    return {str(row[0]) for row in rows if row[0] is not None}


def _matches_ids(column, values: set[str]):
    """Return a SQL predicate that is safely false for an empty identifier set."""
    return column.in_(values) if values else false()


def _matches_resource_or_run(model, resource_ids: set[str], run_ids: set[str]):
    """Match a model through whichever resource/run foreign keys it exposes."""
    predicates = []
    if resource_ids and hasattr(model, "resource_id"):
        predicates.append(model.resource_id.in_(resource_ids))
    if run_ids and hasattr(model, "run_id"):
        predicates.append(model.run_id.in_(run_ids))
    return or_(*predicates) if predicates else false()


def _orm_to_pydantic(orm: LearnerProfileORM) -> LearnerProfile:
    """将 ORM 对象转换为 Pydantic 模型"""
    return LearnerProfile(
        learner_id=orm.learner_id,
        user_id=orm.user_id,
        learner_type=orm.learner_type,
        education=orm.education,
        major=orm.major,
        target_domain=orm.target_domain,
        knowledge_base_id=orm.knowledge_base_id,
        theory_scores=orm.theory_scores or {},
        knowledge_states={
            key: KnowledgeState(**value)
            for key, value in (orm.knowledge_states or {}).items()
        },
        skill_level=orm.skill_level,
        weak_points=orm.weak_points or [],
        strong_points=orm.strong_points or [],
        learning_goal=orm.learning_goal,
        learning_preferences=LearningPreferences(**orm.learning_preferences)
        if orm.learning_preferences
        else None,
        last_feedback_summary=orm.last_feedback_summary or {},
        profile_version=orm.profile_version or 1,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _pydantic_to_orm(profile: LearnerProfile) -> LearnerProfileORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return LearnerProfileORM(
        learner_id=profile.learner_id,
        user_id=profile.user_id,
        learner_type=profile.learner_type,
        education=profile.education,
        major=profile.major,
        target_domain=profile.target_domain,
        knowledge_base_id=profile.knowledge_base_id,
        theory_scores=profile.theory_scores,
        knowledge_states={
            key: value.model_dump()
            for key, value in profile.knowledge_states.items()
        },
        skill_level=profile.skill_level,
        weak_points=profile.weak_points,
        strong_points=profile.strong_points,
        learning_goal=profile.learning_goal,
        learning_preferences=profile.learning_preferences.model_dump()
        if profile.learning_preferences
        else {},
        last_feedback_summary=profile.last_feedback_summary,
        profile_version=profile.profile_version,
    )


class SQLLearnerRepository(BaseLearnerRepository):
    """基于 SQLAlchemy 的学习者画像仓库"""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=learner_id).first()
        return _orm_to_pydantic(orm) if orm else None

    def save(self, profile: LearnerProfile) -> None:
        with self.session_factory() as db:
            orm = db.query(LearnerProfileORM).filter_by(learner_id=profile.learner_id).first()
            if orm:
                orm.user_id = profile.user_id
                orm.learner_type = profile.learner_type
                orm.education = profile.education
                orm.major = profile.major
                orm.target_domain = profile.target_domain
                orm.knowledge_base_id = profile.knowledge_base_id
                orm.theory_scores = profile.theory_scores
                orm.knowledge_states = {
                    key: value.model_dump()
                    for key, value in profile.knowledge_states.items()
                }
                orm.skill_level = profile.skill_level
                orm.weak_points = profile.weak_points
                orm.strong_points = profile.strong_points
                orm.learning_goal = profile.learning_goal
                orm.learning_preferences = (
                    profile.learning_preferences.model_dump()
                    if profile.learning_preferences
                    else {}
                )
                orm.last_feedback_summary = profile.last_feedback_summary
                orm.profile_version = profile.profile_version
            else:
                orm = _pydantic_to_orm(profile)
                db.add(orm)
            db.commit()

    def delete(self, learner_id: str) -> bool:
        """Permanently remove a profile and every learner-scoped artifact.

        Deletion is deliberately explicit instead of relying on SQL-level
        cascade settings: historical SQLite databases predate several foreign
        keys, and related rows also include JSON-era tables without a physical
        foreign key.  The ordering below keeps strict SQLite foreign-key
        enforcement enabled while covering all current learning, resource,
        workflow, review, and feedback projections.
        """

        with self.session_factory() as db:
            if db.get(LearnerProfileORM, learner_id) is None:
                return False

        staged_files = stage_learner_resource_directories(learner_id)
        try:
            with self.session_factory() as db:
                profile = db.get(LearnerProfileORM, learner_id)
                if profile is None:
                    staged_files.restore()
                    return False

                resource_ids = _ids(
                    db.query(GeneratedResourceORM.resource_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                resource_run_ids = _ids(
                    db.query(GeneratedResourceORM.run_id)
                    .filter(
                        GeneratedResourceORM.learner_id == learner_id,
                        GeneratedResourceORM.run_id.is_not(None),
                    )
                    .all()
                )
                run_ids = _ids(
                    db.query(AgentRunORM.run_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                run_ids.update(
                    _ids(
                        db.query(GenerationJobORM.run_id)
                        .filter_by(learner_id=learner_id)
                        .all()
                    )
                )
                run_ids.update(resource_run_ids)

                attempt_ids = _ids(
                    db.query(LearningAttemptORM.attempt_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                decision_ids = _ids(
                    db.query(FeedbackDecisionORM.decision_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                path_ids = _ids(
                    db.query(LearningPathORM.path_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                submission_ids = _ids(
                    db.query(QuestionnaireSubmissionORM.submission_id)
                    .filter_by(learner_id=learner_id)
                    .all()
                )
                review_ids = _ids(
                    db.query(ResourceReviewORM.review_id)
                    .filter(_matches_resource_or_run(ResourceReviewORM, resource_ids, run_ids))
                    .all()
                )
                claim_ids = _ids(
                    db.query(ResourceClaimORM.claim_id)
                    .filter(
                        _matches_resource_or_run(ResourceClaimORM, resource_ids, run_ids)
                        | _matches_ids(ResourceClaimORM.review_id, review_ids)
                    )
                    .all()
                )
                judgement_ids = _ids(
                    db.query(ClaimJudgementORM.judgement_id)
                    .filter(
                        _matches_resource_or_run(ClaimJudgementORM, resource_ids, run_ids)
                        | _matches_ids(ClaimJudgementORM.claim_id, claim_ids)
                        | _matches_ids(ClaimJudgementORM.review_id, review_ids)
                    )
                    .all()
                )
                evidence_ids = _ids(
                    db.query(RetrievalEvidenceSnapshotORM.evidence_id)
                    .filter(_matches_ids(RetrievalEvidenceSnapshotORM.run_id, run_ids))
                    .all()
                )
                spec_ids = _ids(
                    db.query(ResourceSpecORM.resource_spec_id)
                    .filter(_matches_ids(ResourceSpecORM.run_id, run_ids))
                    .all()
                )

                # Claim and review descendants must disappear before their
                # resources, evidence snapshots, or workflow runs.
                db.query(ClaimEvidenceORM).filter(
                    _matches_ids(ClaimEvidenceORM.judgement_id, judgement_ids)
                    | _matches_ids(ClaimEvidenceORM.claim_id, claim_ids)
                    | _matches_ids(ClaimEvidenceORM.evidence_id, evidence_ids)
                    | _matches_ids(ClaimEvidenceORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(ClaimJudgementORM).filter(
                    _matches_ids(ClaimJudgementORM.judgement_id, judgement_ids)
                    | _matches_ids(ClaimJudgementORM.claim_id, claim_ids)
                    | _matches_ids(ClaimJudgementORM.review_id, review_ids)
                    | _matches_resource_or_run(ClaimJudgementORM, resource_ids, run_ids)
                ).delete(synchronize_session=False)
                db.query(ResourceClaimORM).filter(
                    _matches_ids(ResourceClaimORM.claim_id, claim_ids)
                    | _matches_ids(ResourceClaimORM.review_id, review_ids)
                    | _matches_resource_or_run(ResourceClaimORM, resource_ids, run_ids)
                ).delete(synchronize_session=False)
                db.query(ResourceReviewORM).filter(
                    _matches_ids(ResourceReviewORM.review_id, review_ids)
                    | _matches_resource_or_run(ResourceReviewORM, resource_ids, run_ids)
                ).delete(synchronize_session=False)

                # Feedback-loop descendants reference attempts, decisions,
                # paths and/or runs.  Delete their deepest rows first.
                db.query(FeedbackFollowUpRunORM).filter(
                    _matches_ids(FeedbackFollowUpRunORM.attempt_id, attempt_ids)
                    | _matches_ids(FeedbackFollowUpRunORM.decision_id, decision_ids)
                    | _matches_ids(FeedbackFollowUpRunORM.parent_run_id, run_ids)
                    | _matches_ids(FeedbackFollowUpRunORM.child_run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(LearningPathMutationORM).filter(
                    _matches_ids(LearningPathMutationORM.learner_id, {learner_id})
                    | _matches_ids(LearningPathMutationORM.path_id, path_ids)
                    | _matches_ids(LearningPathMutationORM.attempt_id, attempt_ids)
                    | _matches_ids(LearningPathMutationORM.decision_id, decision_ids)
                ).delete(synchronize_session=False)
                db.query(LearnerProfileVersionORM).filter(
                    _matches_ids(LearnerProfileVersionORM.learner_id, {learner_id})
                    | _matches_ids(LearnerProfileVersionORM.source_attempt_id, attempt_ids)
                    | _matches_ids(LearnerProfileVersionORM.source_decision_id, decision_ids)
                ).delete(synchronize_session=False)
                db.query(KnowledgeStateMutationORM).filter(
                    _matches_ids(KnowledgeStateMutationORM.learner_id, {learner_id})
                    | _matches_ids(KnowledgeStateMutationORM.attempt_id, attempt_ids)
                ).delete(synchronize_session=False)
                db.query(FeedbackDecisionORM).filter(
                    _matches_ids(FeedbackDecisionORM.learner_id, {learner_id})
                    | _matches_ids(FeedbackDecisionORM.attempt_id, attempt_ids)
                ).delete(synchronize_session=False)
                db.query(LearningAttemptPointResultORM).filter(
                    _matches_ids(LearningAttemptPointResultORM.attempt_id, attempt_ids)
                ).delete(synchronize_session=False)
                db.query(LearningAttemptORM).filter(
                    _matches_ids(LearningAttemptORM.learner_id, {learner_id})
                    | _matches_ids(LearningAttemptORM.source_resource_id, resource_ids)
                    | _matches_ids(LearningAttemptORM.source_run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(LearningPathNodeORM).filter(
                    _matches_ids(LearningPathNodeORM.path_id, path_ids)
                ).delete(synchronize_session=False)
                db.query(LearningPathORM).filter(
                    _matches_ids(LearningPathORM.learner_id, {learner_id})
                ).delete(synchronize_session=False)
                db.query(FeedbackRecordORM).filter_by(
                    learner_id=learner_id
                ).delete(synchronize_session=False)

                # Questionnaire and diagnosis history is profile-owned.
                db.query(QuestionnaireAnswerORM).filter(
                    _matches_ids(QuestionnaireAnswerORM.submission_id, submission_ids)
                ).delete(synchronize_session=False)
                db.query(QuestionnaireSubmissionORM).filter_by(
                    learner_id=learner_id
                ).delete(synchronize_session=False)
                db.query(DiagnosticAnswerORM).filter_by(
                    learner_id=learner_id
                ).delete(synchronize_session=False)
                db.query(KnowledgeStateORM).filter_by(
                    learner_id=learner_id
                ).delete(synchronize_session=False)
                db.query(DiagnosticRunORM).filter_by(
                    learner_id=learner_id
                ).delete(synchronize_session=False)

                # Resource-workflow descendants precede resources and runs.
                db.query(ResourceExecutionORM).filter(
                    _matches_ids(ResourceExecutionORM.run_id, run_ids)
                    | _matches_ids(ResourceExecutionORM.resource_spec_id, spec_ids)
                    | _matches_ids(ResourceExecutionORM.resource_id, resource_ids)
                ).delete(synchronize_session=False)
                db.query(GeneratedResourceORM).filter(
                    _matches_ids(GeneratedResourceORM.parent_resource_id, resource_ids)
                ).update(
                    {
                        GeneratedResourceORM.parent_resource_id: None,
                    },
                    synchronize_session=False,
                )
                db.query(GeneratedResourceORM).filter(
                    _matches_ids(GeneratedResourceORM.resource_id, resource_ids)
                    | _matches_ids(GeneratedResourceORM.learner_id, {learner_id})
                ).delete(synchronize_session=False)
                db.query(ResourceSpecORM).filter(
                    _matches_ids(ResourceSpecORM.run_id, run_ids)
                ).delete(synchronize_session=False)

                # Complete the audit/run subtree after all records that refer
                # to steps or runs have been removed.
                db.query(ContestEvalResultORM).filter(
                    _matches_ids(ContestEvalResultORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(WorkflowCheckpointORM).filter(
                    _matches_ids(WorkflowCheckpointORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(WorkflowEventORM).filter(
                    _matches_ids(WorkflowEventORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(RetrievalEvidenceSnapshotORM).filter(
                    _matches_ids(RetrievalEvidenceSnapshotORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(AgentStepORM).filter(
                    _matches_ids(AgentStepORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(GenerationJobORM).filter(
                    _matches_ids(GenerationJobORM.learner_id, {learner_id})
                    | _matches_ids(GenerationJobORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.query(AgentRunORM).filter(
                    _matches_ids(AgentRunORM.learner_id, {learner_id})
                    | _matches_ids(AgentRunORM.run_id, run_ids)
                ).delete(synchronize_session=False)
                db.delete(profile)
                db.commit()
        except Exception:
            staged_files.restore()
            raise

        try:
            staged_files.finalize()
        except OSError:
            # The database has committed; staged files are no longer readable
            # from any resource endpoint.  Keep the failure observable without
            # falsely reporting a rollback that cannot happen at this point.
            logger.exception("Failed to finalize deleted learner resource files learner_id=%s", learner_id)
        return True

    def list_all(self) -> Dict[str, LearnerProfile]:
        with self.session_factory() as db:
            orms = db.query(LearnerProfileORM).all()
        return {orm.learner_id: _orm_to_pydantic(orm) for orm in orms}

    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        profile = self.get(learner_id)
        if profile is None:
            return None
        updated = profile.model_copy(update=updates)
        self.save(updated)
        return updated

    def list_with_pagination(
        self,
        page: int,
        page_size: int,
        skill_level: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        with self.session_factory() as db:
            query = db.query(LearnerProfileORM)
            if user_id:
                query = query.filter_by(user_id=user_id)
            if skill_level:
                query = query.filter_by(skill_level=skill_level)
            total = query.count()
            rows = query.order_by(LearnerProfileORM.learner_id).offset((page - 1) * page_size).limit(page_size).all()
        return {"total": total, "page": page, "page_size": page_size, "items": [_orm_to_pydantic(row) for row in rows]}
