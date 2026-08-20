"""SQLAlchemy Tutor repository with atomic session progression."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import TutorSessionORM, TutorTurnORM
from app.db.tutor.base import (
    BaseTutorRepository,
    TutorIdempotencyConflict,
    TutorPersistenceConflict,
)
from app.models.tutor import TutorEvidenceRef, TutorSession, TutorTurn


def _utc(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=timezone.utc)


def _session_schema(row: TutorSessionORM) -> TutorSession:
    return TutorSession(
        schema_version=row.schema_version,
        session_id=row.session_id,
        learner_id=row.learner_id,
        source_type=row.source_type,
        source_resource_id=row.source_resource_id,
        source_run_id=row.source_run_id,
        source_batch_id=row.source_batch_id,
        knowledge_base_id=row.knowledge_base_id,
        context_type=row.context_type,
        question_id=row.question_id,
        skill_node_id=row.skill_node_id,
        path_node_id=row.path_node_id,
        knowledge_point=row.knowledge_point,
        status=row.status,
        current_hint_level=row.current_hint_level,
        turn_count=row.turn_count,
        created_at=_utc(row.created_at),
        updated_at=_utc(row.updated_at),
        closed_at=_utc(row.closed_at),
    )


def _turn_schema(row: TutorTurnORM) -> TutorTurn:
    return TutorTurn(
        schema_version=row.schema_version,
        turn_id=row.turn_id,
        session_id=row.session_id,
        sequence=row.sequence,
        client_message_id=row.client_message_id,
        request_hash=row.request_hash,
        user_message=row.user_message,
        assistant_message=row.assistant_message,
        pedagogy_action=row.pedagogy_action,
        hint_level=row.hint_level,
        follow_up_question=row.follow_up_question,
        target_knowledge_points=row.target_knowledge_points or [],
        grounding_status=row.grounding_status,
        grounding_source=row.grounding_source,
        evidence_refs=[TutorEvidenceRef(**item) for item in (row.evidence_refs or [])],
        retrieval_query_hash=row.retrieval_query_hash,
        retrieval_status=row.retrieval_status,
        llm_call_id=row.llm_call_id,
        model_name=row.model_name,
        input_tokens=row.input_tokens,
        output_tokens=row.output_tokens,
        total_tokens=row.total_tokens,
        llm_duration_ms=row.llm_duration_ms,
        retry_count=row.retry_count,
        error_code=row.error_code,
        created_at=_utc(row.created_at),
    )


class SQLTutorRepository(BaseTutorRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def create_session(self, session: TutorSession) -> TutorSession:
        with self.session_factory() as db:
            existing = db.get(TutorSessionORM, session.session_id)
            if existing is not None:
                stored = _session_schema(existing)
                if stored != session:
                    raise TutorPersistenceConflict("tutor session identity conflict")
                return stored
            db.add(TutorSessionORM(**session.model_dump(mode="python")))
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise TutorPersistenceConflict("tutor session constraint conflict") from exc
            row = db.get(TutorSessionORM, session.session_id)
            return _session_schema(row)

    def get_session(self, session_id: str) -> TutorSession | None:
        with self.session_factory() as db:
            row = db.get(TutorSessionORM, session_id)
            return _session_schema(row) if row else None

    def list_sessions(
        self,
        learner_id: str,
        *,
        status: str | None = None,
        source_resource_id: str | None = None,
        source_run_id: str | None = None,
        source_batch_id: str | None = None,
        context_type: str | None = None,
        question_id: str | None = None,
        created_before: datetime | None = None,
    ) -> list[TutorSession]:
        with self.session_factory() as db:
            query = db.query(TutorSessionORM).filter_by(learner_id=learner_id)
            filters = {
                "status": status,
                "source_resource_id": source_resource_id,
                "source_run_id": source_run_id,
                "source_batch_id": source_batch_id,
                "context_type": context_type,
                "question_id": question_id,
            }
            for field, value in filters.items():
                if value is not None:
                    query = query.filter(getattr(TutorSessionORM, field) == value)
            rows = query.order_by(TutorSessionORM.updated_at.desc()).all()
            return [_session_schema(row) for row in rows]

    def update_session_state(
        self,
        session_id: str,
        *,
        status: str | None = None,
        current_hint_level: int | None = None,
        turn_count: int | None = None,
        closed_at: datetime | None = None,
    ) -> TutorSession | None:
        with self.session_factory() as db:
            row = db.query(TutorSessionORM).filter_by(session_id=session_id).with_for_update().first()
            if row is None:
                return None
            if status is not None:
                row.status = status
            if current_hint_level is not None:
                row.current_hint_level = current_hint_level
            if turn_count is not None:
                row.turn_count = turn_count
            if closed_at is not None:
                row.closed_at = closed_at
            row.updated_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(row)
            return _session_schema(row)

    def append_turn(self, turn: TutorTurn) -> TutorTurn:
        with self.session_factory() as db:
            session = (
                db.query(TutorSessionORM)
                .filter_by(session_id=turn.session_id)
                .with_for_update()
                .first()
            )
            if session is None:
                raise TutorPersistenceConflict("tutor session not found")
            existing = (
                db.query(TutorTurnORM)
                .filter_by(
                    session_id=turn.session_id,
                    client_message_id=turn.client_message_id,
                )
                .first()
            )
            if existing is not None:
                stored = _turn_schema(existing)
                if stored.request_hash != turn.request_hash:
                    raise TutorIdempotencyConflict("tutor client message payload conflict")
                return stored
            if session.status != "active":
                raise TutorPersistenceConflict("tutor session is not active")
            if turn.sequence != session.turn_count + 1:
                raise TutorPersistenceConflict("tutor turn sequence conflict")

            values = turn.model_dump(mode="python")
            values["evidence_refs"] = [
                item.model_dump(mode="json") for item in turn.evidence_refs
            ]
            db.add(TutorTurnORM(**values))
            session.turn_count = turn.sequence
            session.current_hint_level = turn.hint_level
            session.updated_at = turn.created_at
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                concurrent = (
                    db.query(TutorTurnORM)
                    .filter_by(
                        session_id=turn.session_id,
                        client_message_id=turn.client_message_id,
                    )
                    .first()
                )
                if concurrent is not None:
                    stored = _turn_schema(concurrent)
                    if stored.request_hash != turn.request_hash:
                        raise TutorIdempotencyConflict(
                            "tutor client message payload conflict"
                        ) from exc
                    return stored
                raise TutorPersistenceConflict("tutor turn constraint conflict") from exc
            row = db.get(TutorTurnORM, turn.turn_id)
            return _turn_schema(row)

    def get_turn_by_client_message_id(
        self,
        session_id: str,
        client_message_id: str,
    ) -> TutorTurn | None:
        with self.session_factory() as db:
            row = (
                db.query(TutorTurnORM)
                .filter_by(
                    session_id=session_id,
                    client_message_id=client_message_id,
                )
                .first()
            )
            return _turn_schema(row) if row else None

    def list_turns(self, session_id: str, *, limit: int = 100) -> list[TutorTurn]:
        with self.session_factory() as db:
            rows = (
                db.query(TutorTurnORM)
                .filter_by(session_id=session_id)
                .order_by(TutorTurnORM.sequence)
                .limit(max(0, limit))
                .all()
            )
            return [_turn_schema(row) for row in rows]

    def count_turns(
        self,
        learner_id: str,
        *,
        source_run_id: str | None = None,
        source_batch_id: str | None = None,
        context_type: str | None = None,
        question_id: str | None = None,
        created_before: datetime | None = None,
    ) -> int:
        with self.session_factory() as db:
            query = (
                db.query(TutorTurnORM)
                .join(TutorSessionORM, TutorSessionORM.session_id == TutorTurnORM.session_id)
                .filter(TutorSessionORM.learner_id == learner_id)
            )
            if source_run_id is not None:
                query = query.filter(TutorSessionORM.source_run_id == source_run_id)
            if source_batch_id is not None:
                query = query.filter(TutorSessionORM.source_batch_id == source_batch_id)
            if context_type is not None:
                query = query.filter(TutorSessionORM.context_type == context_type)
            if question_id is not None:
                query = query.filter(TutorSessionORM.question_id == question_id)
            if created_before is not None:
                query = query.filter(TutorTurnORM.created_at <= created_before)
            return query.count()
