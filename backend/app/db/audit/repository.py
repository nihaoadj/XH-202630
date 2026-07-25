from typing import Callable, Optional

from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.audit.base import BaseAuditRepository
from app.db.audit.memory import MemoryAuditRepository
from app.db.audit.sql_repository import SQLAuditRepository
from app.db.database import get_session_factory


def create_audit_repository(
    db_type: Optional[str] = None,
    session_factory: Optional[Callable[[], Session]] = None,
) -> BaseAuditRepository:
    db_type = db_type or get_settings().db_type
    if db_type == "memory":
        return MemoryAuditRepository()
    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for audit repository: {db_type}")
    return SQLAuditRepository(session_factory or get_session_factory())
