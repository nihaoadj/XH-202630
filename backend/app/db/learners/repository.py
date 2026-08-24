"""学习者画像仓库工厂"""
from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.learners.base import BaseLearnerRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learners.sql_repository import SQLLearnerRepository
from app.db.shared.database import get_session_factory


def create_learner_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseLearnerRepository:
    """根据存储类型创建学习者画像仓库实例。

    该函数是仓储实现选择的唯一入口，供 DI 容器与脚本复用。
    """
    if db_type == "memory":
        return MemoryLearnerRepository()

    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for learner repository: {db_type}")

    if session_factory is None:
        session_factory = get_session_factory()

    return SQLLearnerRepository(session_factory)


@lru_cache()
def get_learner_repository() -> BaseLearnerRepository:
    """获取学习者画像仓库实例

    根据 DB_TYPE 配置自动选择实现：
    - memory：内存实现，适合开发与演示
    - sqlite / postgresql：SQLAlchemy 实现，数据持久化
    """
    settings = get_settings()
    return create_learner_repository(settings.db_type)
