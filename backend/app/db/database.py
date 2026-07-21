"""数据库引擎与会话管理"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings, resolve_backend_path
from app.db.models import Base


def _resolve_database_url(url: str) -> str:
    """将相对路径的 SQLite URL 解析为基于 backend 目录的绝对路径

    例如 sqlite:///./data/domain_knowledge.db 会被解析为
    sqlite:///{backend_dir}/data/domain_knowledge.db，
    确保无论从项目根目录还是 backend 目录运行脚本，数据库位置都一致。
    """
    if not url.startswith("sqlite:///") or url.startswith("sqlite:////"):
        return url

    relative_path = url.replace("sqlite:///", "")
    if not relative_path.startswith(("./", ".\\")):
        return url

    absolute_path = resolve_backend_path(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{absolute_path.as_posix()}"


def get_engine():
    """获取数据库引擎"""
    settings = get_settings()
    database_url = _resolve_database_url(settings.database_url)
    return create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        echo=settings.debug,
    )


def get_session_factory():
    """获取会话工厂"""
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db_session():
    """获取一个数据库会话（用于依赖注入）"""
    Session = get_session_factory()
    db = Session()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """初始化数据库表结构"""
    Base.metadata.create_all(bind=get_engine())
