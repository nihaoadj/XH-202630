"""SQLAlchemy 实现的生成资源仓库"""
from typing import List, Optional, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import GeneratedResourceORM
from app.db.resource.base import BaseResourceRepository
from app.models.schemas import ExerciseItem, LearningResource, SourceRef
from app.agents.validators import immutable_resource_payload
from app.db.audit.base import PersistenceConflict


def _orm_to_pydantic(orm: GeneratedResourceORM) -> LearningResource:
    """将 ORM 对象转换为 Pydantic 模型"""
    return LearningResource(
        resource_id=orm.resource_id,
        learner_id=orm.learner_id,
        topic=orm.topic,
        resource_type=orm.resource_type,
        difficulty=orm.difficulty,
        storage_type=orm.storage_type,
        content_text=orm.content_text,
        file_path=orm.file_path,
        file_size=orm.file_size,
        mime_type=orm.mime_type,
        knowledge_points=orm.knowledge_points or [],
        source_refs=[SourceRef(**ref) for ref in (orm.source_refs or [])],
        learning_path_node=orm.learning_path_node,
        review_status=orm.review_status,
        review_id=orm.review_id,
        publication_status=orm.publication_status or "unpublished",
        published_at=orm.published_at,
        run_id=orm.run_id,
        batch_id=orm.batch_id,
        claim_count=orm.claim_count,
        legacy_reviewer_score=orm.legacy_reviewer_score,
        claim_hallucination_rate=orm.claim_hallucination_rate,
        claim_metric_status=orm.claim_metric_status,
        hallucination_rate=orm.hallucination_rate,
        difficulty_match=orm.difficulty_match,
        version=orm.version or 1,
        parent_resource_id=orm.parent_resource_id,
        created_at=orm.created_at,
        exercise_items=[ExerciseItem(**item) for item in (orm.exercise_items or [])],
    )


def _pydantic_to_orm(
    resource: LearningResource,
    learner_id: str,
    topic: str,
    *,
    run_id: str | None = None,
    batch_id: str | None = None,
    generation_step_id: str | None = None,
) -> GeneratedResourceORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return GeneratedResourceORM(
        resource_id=resource.resource_id,
        run_id=run_id or resource.run_id,
        batch_id=batch_id or resource.batch_id,
        generation_step_id=generation_step_id,
        learner_id=learner_id,
        topic=topic,
        resource_type=resource.resource_type,
        difficulty=resource.difficulty,
        storage_type=resource.storage_type,
        content_text=resource.content_text,
        file_path=resource.file_path,
        file_size=resource.file_size,
        mime_type=resource.mime_type,
        knowledge_points=resource.knowledge_points,
        source_refs=[ref.model_dump() for ref in resource.source_refs],
        learning_path_node=resource.learning_path_node,
        review_status=resource.review_status,
        review_id=resource.review_id,
        publication_status=resource.publication_status,
        published_at=resource.published_at,
        claim_count=resource.claim_count,
        legacy_reviewer_score=resource.legacy_reviewer_score,
        claim_hallucination_rate=resource.claim_hallucination_rate,
        claim_metric_status=resource.claim_metric_status,
        hallucination_rate=resource.hallucination_rate,
        difficulty_match=resource.difficulty_match,
        version=resource.version,
        parent_resource_id=resource.parent_resource_id,
        exercise_items=[item.model_dump() for item in resource.exercise_items],
    )


class SQLResourceRepository(BaseResourceRepository):
    """基于 SQLAlchemy 的生成资源仓库"""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, resource_id: str) -> Optional[LearningResource]:
        with self.session_factory() as db:
            orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource_id).first()
        return _orm_to_pydantic(orm) if orm else None

    def save(
        self,
        resource: LearningResource,
        learner_id: str,
        topic: str,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        generation_step_id: str | None = None,
    ) -> None:
        effective_run_id = run_id or resource.run_id
        effective_batch_id = batch_id or resource.batch_id or effective_run_id
        normalized = resource.model_copy(
            update={
                "learner_id": learner_id,
                "topic": topic,
                "run_id": effective_run_id,
                "batch_id": effective_batch_id,
            }
        )
        with self.session_factory() as db:
            try:
                orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource.resource_id).first()
                if effective_run_id is not None:
                    duplicate = (
                        db.query(GeneratedResourceORM)
                        .filter(
                            GeneratedResourceORM.run_id == effective_run_id,
                            GeneratedResourceORM.resource_type == normalized.resource_type,
                            GeneratedResourceORM.version == normalized.version,
                            GeneratedResourceORM.resource_id != normalized.resource_id,
                        )
                        .first()
                    )
                    if duplicate is not None:
                        raise PersistenceConflict("duplicate resource version in run")
                if orm:
                    existing = _orm_to_pydantic(orm)
                    if immutable_resource_payload(existing) != immutable_resource_payload(normalized):
                        raise PersistenceConflict("resource immutable payload conflict")
                    if effective_run_id is not None:
                        if orm.run_id is not None and orm.run_id != effective_run_id:
                            raise PersistenceConflict("resource run_id conflict")
                        orm.run_id = effective_run_id
                    if effective_batch_id is not None:
                        if orm.batch_id is not None and orm.batch_id != effective_batch_id:
                            raise PersistenceConflict("resource batch_id conflict")
                        orm.batch_id = effective_batch_id
                    if generation_step_id is not None:
                        if orm.generation_step_id is not None and orm.generation_step_id != generation_step_id:
                            raise PersistenceConflict("resource generation_step_id conflict")
                        orm.generation_step_id = generation_step_id
                    orm.file_path = resource.file_path
                    orm.file_size = resource.file_size
                    orm.mime_type = resource.mime_type
                    orm.review_status = resource.review_status
                    orm.review_id = resource.review_id
                    orm.publication_status = resource.publication_status
                    orm.published_at = resource.published_at
                    orm.claim_count = resource.claim_count
                    orm.legacy_reviewer_score = resource.legacy_reviewer_score
                    orm.claim_hallucination_rate = resource.claim_hallucination_rate
                    orm.claim_metric_status = resource.claim_metric_status
                    orm.hallucination_rate = resource.hallucination_rate
                    orm.difficulty_match = resource.difficulty_match
                else:
                    orm = _pydantic_to_orm(
                        normalized,
                        learner_id,
                        topic,
                        run_id=effective_run_id,
                        batch_id=effective_batch_id,
                        generation_step_id=generation_step_id,
                    )
                    db.add(orm)
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                if effective_run_id is not None:
                    duplicate = (
                        db.query(GeneratedResourceORM)
                        .filter(
                            GeneratedResourceORM.run_id == effective_run_id,
                            GeneratedResourceORM.resource_type == normalized.resource_type,
                            GeneratedResourceORM.version == normalized.version,
                            GeneratedResourceORM.resource_id != normalized.resource_id,
                        )
                        .first()
                    )
                    if duplicate is not None:
                        raise PersistenceConflict("duplicate resource version in run") from exc
                raise PersistenceConflict("resource persistence constraint conflict") from exc

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        with self.session_factory() as db:
            orms = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
            ).filter(
                GeneratedResourceORM.publication_status.in_(["published"]),
            ).all()
            # Also include resources that have been through review (human_review status)
            # but weren't auto-approved, so user can still see them
            all_orms = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
            ).filter(
                GeneratedResourceORM.review_status.in_([
                    "approved", "human_review", "revision_requested", "pending_review"
                ]),
            ).all()
            # Merge and deduplicate
            seen = set()
            merged = []
            for orm in orms + all_orms:
                if orm.resource_id not in seen:
                    seen.add(orm.resource_id)
                    merged.append(orm)
        return [_orm_to_pydantic(orm) for orm in merged]

    def list_by_run(self, run_id: str) -> List[LearningResource]:
        with self.session_factory() as db:
            orms = (
                db.query(GeneratedResourceORM)
                .filter_by(run_id=run_id)
                .order_by(
                    GeneratedResourceORM.resource_type,
                    GeneratedResourceORM.version,
                    GeneratedResourceORM.resource_id,
                )
                .all()
            )
        return [_orm_to_pydantic(orm) for orm in orms]

    def delete(self, resource_id: str) -> bool:
        with self.session_factory() as db:
            orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource_id).first()
            if orm:
                db.delete(orm)
                db.commit()
                return True
            return False

    def list_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[LearningResource]:
        from sqlalchemy import or_
        with self.session_factory() as db:
            query = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
            ).filter(
                # Show resources that are published OR have been through review
                or_(
                    GeneratedResourceORM.publication_status == "published",
                    GeneratedResourceORM.review_status.in_([
                        "approved", "human_review", "revision_requested", "pending_review"
                    ]),
                ),
            )
            if resource_type:
                query = query.filter_by(resource_type=resource_type)
            if difficulty:
                query = query.filter_by(difficulty=difficulty)
            if run_id:
                query = query.filter_by(run_id=run_id)
            orms = query.order_by(GeneratedResourceORM.created_at.desc()).all()
        return [_orm_to_pydantic(orm) for orm in orms]
