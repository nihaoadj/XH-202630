"""学习反馈仓库工厂"""
from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.database import get_session_factory
from app.db.feedback.base import BaseFeedbackRepository
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.feedback.sql_repository import SQLFeedbackRepository


def create_feedback_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseFeedbackRepository:
    """根据存储类型创建学习反馈仓库实例"""
    if db_type == "memory":
        return MemoryFeedbackRepository()

    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for feedback repository: {db_type}")

    if session_factory is None:
        session_factory = get_session_factory()

    return SQLFeedbackRepository(session_factory)


@lru_cache()
def get_feedback_repository() -> BaseFeedbackRepository:
    """获取学习反馈仓库实例"""
    settings = get_settings()
    return create_feedback_repository(settings.db_type)
