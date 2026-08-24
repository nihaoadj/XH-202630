"""异步资源生成任务仓储工厂"""
from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.shared.database import get_session_factory
from app.db.generation.base import BaseGenerationJobRepository
from app.db.generation.memory import MemoryGenerationJobRepository
from app.db.generation.sql_repository import SQLGenerationJobRepository


def create_generation_job_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseGenerationJobRepository:
    if db_type == "memory":
        return MemoryGenerationJobRepository()

    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for generation job repository: {db_type}")

    if session_factory is None:
        session_factory = get_session_factory()

    return SQLGenerationJobRepository(session_factory)


@lru_cache()
def get_generation_job_repository() -> BaseGenerationJobRepository:
    settings = get_settings()
    return create_generation_job_repository(settings.db_type)
