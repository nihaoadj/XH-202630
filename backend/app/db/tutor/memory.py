"""In-memory Tutor repository for deterministic tests and ephemeral mode."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.tutor.base import (
    BaseTutorRepository,
    TutorIdempotencyConflict,
    TutorPersistenceConflict,
)
from app.models.tutor import TutorSession, TutorTurn


class MemoryTutorRepository(BaseTutorRepository):
    def __init__(self):
        self._sessions: dict[str, TutorSession] = {}
        self._turns: dict[str, list[TutorTurn]] = {}

    def create_session(self, session: TutorSession) -> TutorSession:
        existing = self._sessions.get(session.session_id)
        if existing is not None:
            if existing != session:
                raise TutorPersistenceConflict("tutor session identity conflict")
            return existing.model_copy(deep=True)
        self._sessions[session.session_id] = session.model_copy(deep=True)
        self._turns[session.session_id] = []
        return session.model_copy(deep=True)

    def get_session(self, session_id: str) -> TutorSession | None:
        session = self._sessions.get(session_id)
        return session.model_copy(deep=True) if session else None

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
        sessions = [
            item.model_copy(deep=True)
            for item in self._sessions.values()
            if item.learner_id == learner_id
            and (status is None or item.status == status)
            and (
                source_resource_id is None
                or item.source_resource_id == source_resource_id
            )
            and (source_run_id is None or item.source_run_id == source_run_id)
            and (source_batch_id is None or item.source_batch_id == source_batch_id)
            and (context_type is None or item.context_type == context_type)
            and (question_id is None or item.question_id == question_id)
        ]
        return sorted(sessions, key=lambda item: item.updated_at, reverse=True)

    def update_session_state(
        self,
        session_id: str,
        *,
        status: str | None = None,
        current_hint_level: int | None = None,
        turn_count: int | None = None,
        closed_at: datetime | None = None,
    ) -> TutorSession | None:
        session = self._sessions.get(session_id)
        if session is None:
            return None
        updates = {"updated_at": datetime.now(timezone.utc)}
        if status is not None:
            updates["status"] = status
        if current_hint_level is not None:
            updates["current_hint_level"] = current_hint_level
        if turn_count is not None:
            updates["turn_count"] = turn_count
        if closed_at is not None:
            updates["closed_at"] = closed_at
        updated = session.model_copy(update=updates)
        self._sessions[session_id] = updated
        return updated.model_copy(deep=True)

    def append_turn(self, turn: TutorTurn) -> TutorTurn:
        session = self._sessions.get(turn.session_id)
        if session is None:
            raise TutorPersistenceConflict("tutor session not found")
        existing = self.get_turn_by_client_message_id(
            turn.session_id,
            turn.client_message_id,
        )
        if existing is not None:
            if existing.request_hash != turn.request_hash:
                raise TutorIdempotencyConflict("tutor client message payload conflict")
            return existing
        if session.status != "active":
            raise TutorPersistenceConflict("tutor session is not active")
        if turn.sequence != session.turn_count + 1:
            raise TutorPersistenceConflict("tutor turn sequence conflict")
        self._turns.setdefault(turn.session_id, []).append(turn.model_copy(deep=True))
        self._sessions[turn.session_id] = session.model_copy(
            update={
                "turn_count": turn.sequence,
                "current_hint_level": turn.hint_level,
                "updated_at": turn.created_at,
            }
        )
        return turn.model_copy(deep=True)

    def get_turn_by_client_message_id(
        self,
        session_id: str,
        client_message_id: str,
    ) -> TutorTurn | None:
        for turn in self._turns.get(session_id, []):
            if turn.client_message_id == client_message_id:
                return turn.model_copy(deep=True)
        return None

    def list_turns(self, session_id: str, *, limit: int = 100) -> list[TutorTurn]:
        return [
            item.model_copy(deep=True)
            for item in self._turns.get(session_id, [])[: max(0, limit)]
        ]

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
        session_ids = {
            session.session_id
            for session in self._sessions.values()
            if session.learner_id == learner_id
            and (source_run_id is None or session.source_run_id == source_run_id)
            and (source_batch_id is None or session.source_batch_id == source_batch_id)
            and (context_type is None or session.context_type == context_type)
            and (question_id is None or session.question_id == question_id)
        }
        return sum(
            1
            for session_id in session_ids
            for turn in self._turns.get(session_id, [])
            if created_before is None or turn.created_at <= created_before
        )
