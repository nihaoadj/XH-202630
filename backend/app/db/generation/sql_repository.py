"""异步生成任务仓储的 SQLAlchemy 实现。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Optional

from sqlalchemy.orm import Session

from app.db.generation.base import BaseGenerationJobRepository
from app.db.generation.dispatch import GenerationDispatchMixin
from app.db.generation.fencing import install_execution_fencing
from app.db.shared.models import GenerationJobORM, AgentRunORM
from app.models.learning_documents.schemas import GenerationJobStatusResponse


def _to_schema(orm: GenerationJobORM) -> GenerationJobStatusResponse:
    request_payload = orm.request_payload or {}
    return GenerationJobStatusResponse(
        run_id=orm.run_id,
        batch_id=orm.batch_id,
        learner_id=orm.learner_id,
        topic=orm.topic,
        knowledge_base_id=orm.knowledge_base_id,
        job_status=orm.status,
        resource_ids=orm.resource_ids or [],
        error_message=orm.error_message,
        superseded_by_run_id=orm.superseded_by_run_id,
        request_payload=request_payload,
        focus_snapshot=(request_payload.get("constraints") or {}).get("learner_focus_snapshot"),
        created_at=orm.created_at,
        started_at=orm.started_at,
        finished_at=orm.finished_at,
    )


class SQLGenerationJobRepository(GenerationDispatchMixin, BaseGenerationJobRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory
        install_execution_fencing()

    def create(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
        batch_id: str | None = None,
        *, dispatch_snapshot: dict | None = None, submission_hash: str | None = None,
        retry_of_run_id: str | None = None,
    ) -> None:
        with self.session_factory() as db:
            db.add(
                GenerationJobORM(
                    run_id=run_id,
                    batch_id=batch_id or run_id,
                    learner_id=learner_id,
                    topic=topic,
                    knowledge_base_id=knowledge_base_id,
                    status="queued",
                    request_payload=request_payload,
                    resource_ids=[],
                    dispatch_mode="worker" if dispatch_snapshot else "legacy",
                    dispatch_snapshot=dispatch_snapshot, submission_hash=submission_hash,
                    retry_of_run_id=retry_of_run_id,
                )
            )
            db.commit()

    def create_failed(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
        error_message: str,
        batch_id: str | None = None,
    ) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = GenerationJobORM(
                run_id=run_id,
                batch_id=batch_id or run_id,
                learner_id=learner_id,
                topic=topic,
                knowledge_base_id=knowledge_base_id,
                status="failed",
                error_message=error_message,
                request_payload=request_payload,
                resource_ids=[],
                finished_at=datetime.now(timezone.utc),
            )
            db.add(orm)
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def get(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
        return _to_schema(orm) if orm else None

    def mark_running(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).first()
            if orm is None:
                return None
            if orm.status in {"failed", "completed"}:
                return _to_schema(orm)
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
            if orm.status in {"failed", "completed"}:
                return _to_schema(orm)
            run = db.get(AgentRunORM, run_id)
            if run and run.status in {"failed", "interrupted"}:
                return _to_schema(orm)
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
            if orm.status in {"failed", "completed"}:
                return _to_schema(orm)
            run = db.get(AgentRunORM, run_id)
            if run and run.status in {"completed", "degraded", "human_review"}:
                return _to_schema(orm)
            orm.status = "failed"
            orm.error_message = error_message
            orm.finished_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def mark_queued(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).with_for_update().first()
            if orm is None:
                return None
            run = db.get(AgentRunORM, run_id)
            if run and run.status in {"failed", "interrupted", "completed", "degraded", "human_review"}:
                raise ValueError("terminal run requires a new attempt")
            orm.status = "queued"
            orm.error_message = None
            orm.started_at = None
            orm.finished_at = None
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def mark_superseded(
        self,
        run_id: str,
        replacement_run_id: str,
    ) -> Optional[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            orm = db.query(GenerationJobORM).filter_by(run_id=run_id).with_for_update().first()
            if orm is None:
                return None
            orm.superseded_by_run_id = replacement_run_id
            db.commit()
            db.refresh(orm)
            return _to_schema(orm)

    def fail_incomplete_before(self, before: datetime, error_message: str) -> list[str]:
        # Legacy entry point now delegates to the same lease-aware facts.
        seconds = max(0, int((datetime.now(timezone.utc) - before.replace(tzinfo=before.tzinfo or timezone.utc)).total_seconds()))
        return self.reconcile(queued_timeout_seconds=seconds)["failed_run_ids"]

    def list_by_learner(self, learner_id: str) -> list[GenerationJobStatusResponse]:
        with self.session_factory() as db:
            rows = (
                db.query(GenerationJobORM)
                .filter_by(learner_id=learner_id)
                .order_by(GenerationJobORM.created_at.desc())
                .all()
            )
        return [_to_schema(row) for row in rows]
