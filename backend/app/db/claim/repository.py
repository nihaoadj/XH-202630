from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.claim.base import BaseClaimRepository
from app.db.claim.memory import MemoryClaimRepository
from app.db.claim.sql_repository import SQLClaimRepository
from app.db.database import get_session_factory


def create_claim_repository(db_type: str, session_factory: Callable | None = None) -> BaseClaimRepository:
    if db_type == "memory":
        return MemoryClaimRepository()
    if db_type not in {"sqlite", "postgresql"}:
        raise ValueError(f"Unsupported DB_TYPE for claim repository: {db_type}")
    return SQLClaimRepository(session_factory or get_session_factory())


@lru_cache()
def get_claim_repository() -> BaseClaimRepository:
    return create_claim_repository(get_settings().db_type)
