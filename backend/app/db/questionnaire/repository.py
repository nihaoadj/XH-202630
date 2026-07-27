"""问卷仓储工厂。"""
from typing import Callable

from app.db.questionnaire.base import BaseQuestionnaireRepository
from app.db.questionnaire.memory import MemoryQuestionnaireRepository
from app.db.questionnaire.sql_repository import SQLQuestionnaireRepository


def create_questionnaire_repository(
    db_type: str, session_factory: Callable | None = None
) -> BaseQuestionnaireRepository:
    if db_type == "memory":
        return MemoryQuestionnaireRepository()
    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for questionnaire repository: {db_type}")
    if session_factory is None:
        from app.db.database import get_session_factory

        session_factory = get_session_factory()
    return SQLQuestionnaireRepository(session_factory)
