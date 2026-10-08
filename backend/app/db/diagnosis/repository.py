"""诊断仓库工厂。"""
from typing import Callable

from app.db.diagnosis.base import BaseDiagnosisRepository
from app.db.diagnosis.memory import MemoryDiagnosisRepository
from app.db.diagnosis.sql_repository import SQLDiagnosisRepository


def create_diagnosis_repository(
    db_type: str, session_factory: Callable | None = None
) -> BaseDiagnosisRepository:
    if db_type == "memory":
        return MemoryDiagnosisRepository()
    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for diagnosis repository: {db_type}")
    if session_factory is None:
        from app.db.shared.database import get_session_factory

        session_factory = get_session_factory()
    return SQLDiagnosisRepository(session_factory)
