"""数据库引擎与会话管理"""
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy import text
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


@lru_cache()
def get_engine():
    """获取数据库引擎"""
    settings = get_settings()
    database_url = _resolve_database_url(settings.database_url)
    return create_engine(
        database_url,
        connect_args={"check_same_thread": False} if database_url.startswith("sqlite") else {},
        echo=settings.sql_echo,
        hide_parameters=True,
    )


@lru_cache()
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
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    if engine.url.get_backend_name() == "sqlite":
        _migrate_sqlite_learner_profiles(engine)
        _migrate_sqlite_questionnaire_submissions(engine)


def _migrate_sqlite_learner_profiles(engine) -> None:
    """补齐旧版 SQLite learner_profiles 表缺失的画像字段。"""
    expected_columns = {
        "learner_type": "VARCHAR(64) NOT NULL DEFAULT '问卷学习者'",
        "target_domain": "VARCHAR(128)",
        "knowledge_base_id": "VARCHAR(128)",
        "knowledge_states": "JSON DEFAULT '{}'",
        "learning_preferences": "JSON DEFAULT '{}'",
        "last_feedback_summary": "JSON DEFAULT '{}'",
    }
    with engine.begin() as conn:
        existing = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(learner_profiles)").fetchall()
        }
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE learner_profiles ADD COLUMN {column} {ddl}"))


def _migrate_sqlite_questionnaire_submissions(engine) -> None:
    """修正开发期问卷提交表的字段命名。"""
    with engine.begin() as conn:
        tables = {row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if "questionnaire_submissions" not in tables:
            return
        existing = {
            row[1]
            for row in conn.exec_driver_sql("PRAGMA table_info(questionnaire_submissions)").fetchall()
        }
        if "learning_direction_id" in existing and "track_id" not in existing:
            conn.execute(text("ALTER TABLE questionnaire_submissions RENAME COLUMN learning_direction_id TO track_id"))
