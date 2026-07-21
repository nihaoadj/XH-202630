"""SQLAlchemy 实现的生成资源仓库"""
from typing import List, Optional, Callable

from sqlalchemy.orm import Session

from app.db.models import GeneratedResourceORM
from app.db.resource.base import BaseResourceRepository
from app.models.schemas import LearningResource, SourceRef


def _orm_to_pydantic(orm: GeneratedResourceORM) -> LearningResource:
    """将 ORM 对象转换为 Pydantic 模型"""
    return LearningResource(
        resource_id=orm.resource_id,
        resource_type=orm.resource_type,
        difficulty=orm.difficulty,
        storage_type=orm.storage_type,
        content_text=orm.content_text,
        file_path=orm.file_path,
        file_size=orm.file_size,
        mime_type=orm.mime_type,
        knowledge_points=orm.knowledge_points or [],
        source_refs=[SourceRef(**ref) for ref in (orm.source_refs or [])],
    )


def _pydantic_to_orm(resource: LearningResource, learner_id: str, topic: str) -> GeneratedResourceORM:
    """将 Pydantic 模型转换为 ORM 对象"""
    return GeneratedResourceORM(
        resource_id=resource.resource_id,
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
    )


class SQLResourceRepository(BaseResourceRepository):
    """基于 SQLAlchemy 的生成资源仓库"""

    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def get(self, resource_id: str) -> Optional[LearningResource]:
        with self.session_factory() as db:
            orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource_id).first()
        return _orm_to_pydantic(orm) if orm else None

    def save(self, resource: LearningResource, learner_id: str, topic: str) -> None:
        with self.session_factory() as db:
            orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource.resource_id).first()
            if orm:
                orm.resource_type = resource.resource_type
                orm.difficulty = resource.difficulty
                orm.storage_type = resource.storage_type
                orm.content_text = resource.content_text
                orm.file_path = resource.file_path
                orm.file_size = resource.file_size
                orm.mime_type = resource.mime_type
                orm.knowledge_points = resource.knowledge_points
                orm.source_refs = [ref.model_dump() for ref in resource.source_refs]
            else:
                orm = _pydantic_to_orm(resource, learner_id, topic)
                db.add(orm)
            db.commit()

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        with self.session_factory() as db:
            orms = db.query(GeneratedResourceORM).filter_by(learner_id=learner_id).all()
        return [_orm_to_pydantic(orm) for orm in orms]

    def delete(self, resource_id: str) -> bool:
        with self.session_factory() as db:
            orm = db.query(GeneratedResourceORM).filter_by(resource_id=resource_id).first()
            if orm:
                db.delete(orm)
                db.commit()
                return True
            return False
