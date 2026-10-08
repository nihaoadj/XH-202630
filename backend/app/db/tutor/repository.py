"""Tutor repository factory following the existing storage selection pattern."""

from __future__ import annotations

from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.shared.database import get_session_factory
from app.db.tutor.base import BaseTutorRepository
from app.db.tutor.memory import MemoryTutorRepository
from app.db.tutor.sql_repository import SQLTutorRepository


def create_tutor_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseTutorRepository:
    if db_type == "memory":
        return MemoryTutorRepository()
    if db_type not in {"sqlite", "postgresql"}:
        raise ValueError(f"Unsupported DB_TYPE for tutor repository: {db_type}")
    return SQLTutorRepository(session_factory or get_session_factory())


@lru_cache()
def get_tutor_repository() -> BaseTutorRepository:
    return create_tutor_repository(get_settings().db_type)
