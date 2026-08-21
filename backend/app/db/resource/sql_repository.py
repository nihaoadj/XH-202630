"""SQLAlchemy 实现的生成资源仓库"""
from typing import List, Optional, Callable

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import GeneratedResourceORM, ResourceExecutionORM, ResourceSpecORM
from app.db.resource.base import BaseResourceRepository
from app.db.resource.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.schemas import ExerciseItem, LearningResource, SourceRef
from app.agents.validators import immutable_resource_payload
from app.db.audit.base import PersistenceConflict


def _spec_orm_to_record(orm: ResourceSpecORM) -> ResourceSpecRecord:
    return ResourceSpecRecord(
        schema_version=orm.schema_version or "1.0",
        resource_spec_id=orm.resource_spec_id,
        run_id=orm.run_id,
        resource_family_id=orm.resource_family_id,
        resource_type=orm.resource_type,
        learning_objective=orm.learning_objective,
        knowledge_points=orm.knowledge_points or [],
        evidence_ids=orm.evidence_ids or [],
        difficulty=orm.difficulty,
        representations=orm.representations or [],
        dependencies=orm.dependencies or [],
        display_order=orm.display_order or 0,
        created_at=orm.created_at,
    )


def _execution_orm_to_record(orm: ResourceExecutionORM) -> ResourceExecutionRecord:
    return ResourceExecutionRecord(
        schema_version=orm.schema_version or "1.0",
        execution_id=orm.execution_id,
        run_id=orm.run_id,
        resource_spec_id=orm.resource_spec_id,
        resource_type=orm.resource_type,
        representation=orm.representation or "text",
        worker_step_id=orm.worker_step_id,
        state=orm.state,
        attempt=orm.attempt or 0,
        resource_id=orm.resource_id,
        review_id=orm.review_id,
        error_code=orm.error_code,
        agent_name=orm.agent_name,
        prompt_version=orm.prompt_version,
        artifact_format=orm.artifact_format,
        validation_status=orm.validation_status or "pending",
        renderer_version=orm.renderer_version,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
    )


def _execution_record_to_orm(execution: ResourceExecutionRecord) -> ResourceExecutionORM:
    return ResourceExecutionORM(
        execution_id=execution.execution_id,
        run_id=execution.run_id,
        resource_spec_id=execution.resource_spec_id,
        resource_type=execution.resource_type,
        representation=execution.representation,
        worker_step_id=execution.worker_step_id,
        state=execution.state,
        attempt=execution.attempt,
        resource_id=execution.resource_id,
        review_id=execution.review_id,
        error_code=execution.error_code,
        agent_name=execution.agent_name,
        prompt_version=execution.prompt_version,
        artifact_format=execution.artifact_format,
        validation_status=execution.validation_status,
        renderer_version=execution.renderer_version,
        schema_version=execution.schema_version,
    )


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
        resource_spec_id=orm.resource_spec_id,
        resource_family_id=orm.resource_family_id,
        representation=orm.representation or "text",
        derived_from_resource_id=orm.derived_from_resource_id,
        source_resource_version=orm.source_resource_version,
        canonical_text_hash=orm.canonical_text_hash,
        guide_manifest=orm.guide_manifest or {},
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
        resource_spec_id=resource.resource_spec_id,
        resource_family_id=resource.resource_family_id,
        representation=resource.representation.value
        if hasattr(resource.representation, "value")
        else resource.representation,
        derived_from_resource_id=resource.derived_from_resource_id,
        source_resource_version=resource.source_resource_version,
        canonical_text_hash=resource.canonical_text_hash,
        guide_manifest=resource.guide_manifest,
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
                    duplicate_query = db.query(GeneratedResourceORM).filter(
                        GeneratedResourceORM.run_id == effective_run_id,
                        GeneratedResourceORM.version == normalized.version,
                        GeneratedResourceORM.resource_id != normalized.resource_id,
                    )
                    if normalized.resource_spec_id is not None:
                        representation = (
                            normalized.representation.value
                            if hasattr(normalized.representation, "value")
                            else normalized.representation
                        )
                        duplicate_query = duplicate_query.filter(
                            GeneratedResourceORM.resource_spec_id == normalized.resource_spec_id,
                            GeneratedResourceORM.representation == representation,
                        )
                    else:
                        duplicate_query = duplicate_query.filter(
                            GeneratedResourceORM.resource_spec_id.is_(None),
                            GeneratedResourceORM.resource_type == normalized.resource_type,
                        )
                    duplicate = duplicate_query.first()
                    if duplicate is not None:
                        raise PersistenceConflict("duplicate resource version in run")
                if orm:
                    existing = _orm_to_pydantic(orm)
                    if immutable_resource_payload(existing) != immutable_resource_payload(normalized):
                        raise PersistenceConflict("resource immutable payload conflict")
                    immutable_representation_fields = (
                        "resource_spec_id",
                        "resource_family_id",
                        "representation",
                        "derived_from_resource_id",
                        "source_resource_version",
                        "canonical_text_hash",
                        "guide_manifest",
                    )
                    if any(
                        getattr(existing, field) != getattr(normalized, field)
                        for field in immutable_representation_fields
                    ):
                        raise PersistenceConflict("resource representation identity conflict")
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
                    duplicate_query = db.query(GeneratedResourceORM).filter(
                        GeneratedResourceORM.run_id == effective_run_id,
                        GeneratedResourceORM.version == normalized.version,
                        GeneratedResourceORM.resource_id != normalized.resource_id,
                    )
                    if normalized.resource_spec_id is not None:
                        representation = (
                            normalized.representation.value
                            if hasattr(normalized.representation, "value")
                            else normalized.representation
                        )
                        duplicate_query = duplicate_query.filter(
                            GeneratedResourceORM.resource_spec_id == normalized.resource_spec_id,
                            GeneratedResourceORM.representation == representation,
                        )
                    else:
                        duplicate_query = duplicate_query.filter(
                            GeneratedResourceORM.resource_spec_id.is_(None),
                            GeneratedResourceORM.resource_type == normalized.resource_type,
                        )
                    duplicate = duplicate_query.first()
                    if duplicate is not None:
                        raise PersistenceConflict("duplicate resource version in run") from exc
                raise PersistenceConflict("resource persistence constraint conflict") from exc

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        with self.session_factory() as db:
            orms = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
                publication_status="published",
            ).all()
        return [_orm_to_pydantic(orm) for orm in orms]

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
        with self.session_factory() as db:
            query = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
                publication_status="published",
            )
            if resource_type:
                query = query.filter_by(resource_type=resource_type)
            if difficulty:
                query = query.filter_by(difficulty=difficulty)
            if run_id:
                query = query.filter_by(run_id=run_id)
            orms = query.order_by(GeneratedResourceORM.created_at.desc()).all()
        return [_orm_to_pydantic(orm) for orm in orms]

    def list_page_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[List[LearningResource], int]:
        with self.session_factory() as db:
            query = db.query(GeneratedResourceORM).filter_by(
                learner_id=learner_id,
                publication_status="published",
            )
            if resource_type:
                query = query.filter_by(resource_type=resource_type)
            if difficulty:
                query = query.filter_by(difficulty=difficulty)
            if run_id:
                query = query.filter_by(run_id=run_id)
            total = query.with_entities(func.count(GeneratedResourceORM.resource_id)).scalar() or 0
            orms = (
                query.order_by(
                    GeneratedResourceORM.created_at.desc(),
                    GeneratedResourceORM.resource_id,
                )
                .offset(offset)
                .limit(limit)
                .all()
            )
        return [_orm_to_pydantic(orm) for orm in orms], int(total)

    def save_spec(self, spec: ResourceSpecRecord) -> None:
        with self.session_factory() as db:
            try:
                orm = db.query(ResourceSpecORM).filter_by(
                    resource_spec_id=spec.resource_spec_id
                ).first()
                payload = spec.model_dump(exclude={"created_at"})
                if orm is not None:
                    existing = _spec_orm_to_record(orm).model_dump(exclude={"created_at"})
                    if existing != payload:
                        raise PersistenceConflict("resource spec immutable payload conflict")
                    return
                db.add(
                    ResourceSpecORM(
                        resource_spec_id=spec.resource_spec_id,
                        run_id=spec.run_id,
                        resource_family_id=spec.resource_family_id,
                        resource_type=spec.resource_type,
                        learning_objective=spec.learning_objective,
                        knowledge_points=spec.knowledge_points,
                        evidence_ids=spec.evidence_ids,
                        difficulty=spec.difficulty,
                        representations=spec.representations,
                        dependencies=spec.dependencies,
                        display_order=spec.display_order,
                        schema_version=spec.schema_version,
                    )
                )
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("resource spec persistence constraint conflict") from exc

    def get_spec(self, resource_spec_id: str) -> Optional[ResourceSpecRecord]:
        with self.session_factory() as db:
            orm = db.query(ResourceSpecORM).filter_by(resource_spec_id=resource_spec_id).first()
            return _spec_orm_to_record(orm) if orm else None

    def list_specs_by_run(self, run_id: str) -> List[ResourceSpecRecord]:
        with self.session_factory() as db:
            orms = (
                db.query(ResourceSpecORM)
                .filter_by(run_id=run_id)
                .order_by(ResourceSpecORM.display_order, ResourceSpecORM.resource_spec_id)
                .all()
            )
            return [_spec_orm_to_record(orm) for orm in orms]

    def upsert_execution(self, execution: ResourceExecutionRecord) -> None:
        with self.session_factory() as db:
            try:
                orm = db.query(ResourceExecutionORM).filter_by(
                    run_id=execution.run_id,
                    resource_spec_id=execution.resource_spec_id,
                    representation=execution.representation,
                ).first()
                if orm is None:
                    db.add(_execution_record_to_orm(execution))
                else:
                    existing = _execution_orm_to_record(orm)
                    immutable_fields = (
                        "execution_id",
                        "run_id",
                        "resource_spec_id",
                        "resource_type",
                        "representation",
                        "agent_name",
                        "prompt_version",
                        "artifact_format",
                    )
                    if any(
                        getattr(existing, field) != getattr(execution, field)
                        for field in immutable_fields
                    ):
                        raise PersistenceConflict("resource execution identity conflict")
                    if execution.attempt < existing.attempt:
                        raise PersistenceConflict("resource execution attempt regression")
                    orm.state = execution.state
                    orm.attempt = execution.attempt
                    orm.worker_step_id = execution.worker_step_id
                    orm.resource_id = execution.resource_id
                    orm.review_id = execution.review_id
                    orm.error_code = execution.error_code
                    orm.validation_status = execution.validation_status
                    orm.renderer_version = execution.renderer_version
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("resource execution persistence constraint conflict") from exc

    def get_execution(
        self,
        run_id: str,
        resource_spec_id: str,
        representation: str,
    ) -> Optional[ResourceExecutionRecord]:
        with self.session_factory() as db:
            orm = db.query(ResourceExecutionORM).filter_by(
                run_id=run_id,
                resource_spec_id=resource_spec_id,
                representation=representation,
            ).first()
            return _execution_orm_to_record(orm) if orm else None

    def get_execution_by_resource(self, resource_id: str) -> Optional[ResourceExecutionRecord]:
        with self.session_factory() as db:
            orm = db.query(ResourceExecutionORM).filter_by(resource_id=resource_id).first()
            return _execution_orm_to_record(orm) if orm else None

    def list_executions_by_run(self, run_id: str) -> List[ResourceExecutionRecord]:
        with self.session_factory() as db:
            orms = (
                db.query(ResourceExecutionORM)
                .filter_by(run_id=run_id)
                .order_by(ResourceExecutionORM.resource_spec_id, ResourceExecutionORM.representation)
                .all()
            )
            return [_execution_orm_to_record(orm) for orm in orms]
