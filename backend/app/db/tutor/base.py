"""Repository contract for Tutor session and turn persistence."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from app.models.tutor import TutorSession, TutorTurn


class TutorPersistenceError(RuntimeError):
    """Sanitized Tutor persistence failure."""


class TutorPersistenceConflict(TutorPersistenceError):
    """A durable Tutor invariant would be violated."""


class TutorIdempotencyConflict(TutorPersistenceConflict):
    """One client_message_id was reused with a different canonical payload."""


class BaseTutorRepository(ABC):
    @abstractmethod
    def create_session(self, session: TutorSession) -> TutorSession:
        pass

    @abstractmethod
    def get_session(self, session_id: str) -> TutorSession | None:
        pass

    @abstractmethod
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
    ) -> list[TutorSession]:
        pass

    @abstractmethod
    def update_session_state(
        self,
        session_id: str,
        *,
        status: str | None = None,
        current_hint_level: int | None = None,
        turn_count: int | None = None,
        closed_at: datetime | None = None,
    ) -> TutorSession | None:
        pass

    @abstractmethod
    def append_turn(self, turn: TutorTurn) -> TutorTurn:
        """Atomically append a turn and advance the owning session state."""

    @abstractmethod
    def get_turn_by_client_message_id(
        self,
        session_id: str,
        client_message_id: str,
    ) -> TutorTurn | None:
        pass

    @abstractmethod
    def list_turns(self, session_id: str, *, limit: int = 100) -> list[TutorTurn]:
        pass

    @abstractmethod
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
        pass
