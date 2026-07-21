"""生成资源仓库工厂"""
from functools import lru_cache
from typing import Callable

from app.config import get_settings
from app.db.database import get_session_factory
from app.db.resource.base import BaseResourceRepository
from app.db.resource.memory import MemoryResourceRepository
from app.db.resource.sql_repository import SQLResourceRepository


def create_resource_repository(
    db_type: str,
    session_factory: Callable | None = None,
) -> BaseResourceRepository:
    """根据存储类型创建生成资源仓库实例。

    该函数是资源仓储实现选择的唯一入口，供 DI 容器与脚本复用。
    """
    if db_type == "memory":
        return MemoryResourceRepository()

    if db_type not in ("sqlite", "postgresql"):
        raise ValueError(f"Unsupported DB_TYPE for resource repository: {db_type}")

    if session_factory is None:
        session_factory = get_session_factory()

    return SQLResourceRepository(session_factory)


@lru_cache()
def get_resource_repository() -> BaseResourceRepository:
    """获取生成资源仓库实例

    根据 DB_TYPE 配置自动选择实现：
    - memory：内存实现，适合开发与演示
    - sqlite / postgresql：SQLAlchemy 实现，数据持久化
    """
    settings = get_settings()
    return create_resource_repository(settings.db_type)
