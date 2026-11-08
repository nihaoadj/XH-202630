"""Repository composition for persistent learning rounds."""

from app.db.feedback.round_memory import MemoryRoundRepository
from app.db.feedback.round_sql_repository import SQLRoundRepository


def create_round_repository(db_type: str, session_factory=None):
    if db_type == "memory":
        return MemoryRoundRepository()
    if db_type in {"sqlite", "postgresql"}:
        if session_factory is None:
            from app.db.shared.database import get_session_factory

            session_factory = get_session_factory()
        return SQLRoundRepository(session_factory)
    raise ValueError(f"unsupported round repository: {db_type}")
