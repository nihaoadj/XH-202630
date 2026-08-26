from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.shared.database import get_session_factory
from app.db.users.base import BaseUserRepository
from app.db.users.memory import MemoryUserRepository
from app.db.users.sql_repository import SQLUserRepository


def create_user_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseUserRepository:
    if db_type == "memory":
        return MemoryUserRepository()
    if db_type not in {"sqlite", "postgresql"}:
        raise ValueError(f"Unsupported db_type for user repository: {db_type}")
    factory = session_factory or get_session_factory()
    return SQLUserRepository(factory)


@lru_cache()
def get_user_repository() -> BaseUserRepository:
    settings = get_settings()
    return create_user_repository(settings.db_type)
