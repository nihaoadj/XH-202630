"""异步生成任务仓储的 SQLAlchemy 实现。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.db.generation_job.base import BaseGenerationJobRepository
from app.db.models import GenerationJobORM
from app.models.schemas import GenerationJobStatusResponse


def _to_schema(orm: GenerationJobORM) -> GenerationJobStatusResponse:
    return GenerationJobStatusResponse(
        run_id=orm.run_id,
        learner_id=orm.learner_id,
        topic=orm.topic,
        knowledge_base_id=orm.knowledge_base_id,
        job_status=orm.status,
        resource_ids=orm.resource_ids or [],
        error_message=orm.error_message,
        request_payload=orm.request_payload or {},
        created_at=orm.created_at,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
    )


class SQLGenerationJobRepository(BaseGenerationJobRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def create(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
    ) -> None:
        with self.session_factory() as db:
            db.add(
                GenerationJobORM(
                    run_id=run_id,
                    learner_id=learner_id,
                    topic=topic,
                    knowledge_base_id=knowledge_base_id,
                    status="queued",
                    request_payload=request_payload,
                    resource_ids=[],
                )
            )
            db.commit()

    def get(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
        return _to_schema(orm) if orm else None

    def mark_running(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
            if orm is None:
                return None
            orm.status = "running"
            orm.started_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def mark_completed(self, run_id: str, resource_ids: list[str]) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
            if orm is None:
                return None
            orm.status = "completed"
            orm.resource_ids = resource_ids
            orm.finished_at = datetime.now(timezone.utc)
            orm.error_message = None
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def mark_failed(self, run_id: str, error_message: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
            if orm is None:
                return None
            orm.status = "failed"
            orm.error_message = error_message
            orm.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def list_by_learner(self, learner_id: str) -> list[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            rows = (
                db.query(GenerationJobORM)
                .filter_by(learner_id=learner_id)
                .order_by(GenerationJobORM.created_at.desc())
                .all()
            )
        return [_to_schema(row) for row in rows]
