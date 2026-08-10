"""数据库引擎、会话工厂与 SQLite 轻量迁移。"""
from functools import lru_cache

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.config import get_settings, resolve_backend_path
from app.db import extended_models  # noqa: F401
from app.db.models import Base
from app.db.migrations import (
    apply_p0_04_migration,
    apply_p0_05_migration,
    apply_p0_06_migration,
    apply_p0_07_migration,
)


def _resolve_database_url(url: str) -> str:
    """将相对 SQLite 路径解析为 backend 目录下的绝对路径。"""
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
    """获取数据库引擎。"""
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
    """获取会话工厂。"""
    return sessionmaker(autocommit=False, autoflush=False, bind=get_engine())


def get_db_session():
    """提供数据库会话依赖。"""
    session_factory = get_session_factory()
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


def init_database():
    """初始化数据库并执行 SQLite 兼容迁移。"""
    engine = get_engine()
    Base.metadata.create_all(bind=engine)
    apply_p0_04_migration(engine)
    apply_p0_05_migration(engine)
    apply_p0_06_migration(engine)
    apply_p0_07_migration(engine)
    if engine.url.get_backend_name() == "sqlite":
        _migrate_sqlite_users(engine)
        _migrate_sqlite_learner_profiles(engine)
        _migrate_sqlite_questionnaire_submissions(engine)
        _migrate_sqlite_generated_resources(engine)
        _migrate_sqlite_generation_jobs(engine)
        _migrate_sqlite_feedback_records(engine)


def _sqlite_tables(conn) -> set[str]:
    return {
        row[0]
        for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }


def _sqlite_columns(conn, table_name: str) -> set[str]:
    return {
        row[1]
        for row in conn.exec_driver_sql(f"PRAGMA table_info({table_name})").fetchall()
    }


def _migrate_sqlite_learner_profiles(engine) -> None:
    """补齐旧版 learner_profiles 缺失的画像字段。"""
    expected_columns = {
        "learner_type": "VARCHAR(64) NOT NULL DEFAULT '问卷学习者'",
        "target_domain": "VARCHAR(128)",
        "knowledge_base_id": "VARCHAR(128)",
        "knowledge_states": "JSON DEFAULT '{}'",
        "learning_preferences": "JSON DEFAULT '{}'",
        "last_feedback_summary": "JSON DEFAULT '{}'",
    }
    with engine.begin() as conn:
        if "learner_profiles" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "learner_profiles")
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE learner_profiles ADD COLUMN {column} {ddl}"))


def _migrate_sqlite_users(engine) -> None:
    """补齐 users 表缺失的用户身份字段。"""
    expected_columns = {
        "identity": "VARCHAR(64) NOT NULL DEFAULT '其他'",
    }
    with engine.begin() as conn:
        if "users" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "users")
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE users ADD COLUMN {column} {ddl}"))


def _migrate_sqlite_questionnaire_submissions(engine) -> None:
    """修正开发期 questionnaire_submissions 的旧字段命名。"""
    with engine.begin() as conn:
        if "questionnaire_submissions" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "questionnaire_submissions")
        if "learning_direction_id" in existing and "track_id" not in existing:
            conn.execute(text("ALTER TABLE questionnaire_submissions RENAME COLUMN learning_direction_id TO track_id"))


def _migrate_sqlite_generated_resources(engine) -> None:
    """为旧版 generated_resources 补齐资源文件化与审核字段。"""
    expected_columns = {
        "storage_type": "VARCHAR(16) NOT NULL DEFAULT 'text'",
        "content_text": "VARCHAR",
        "file_path": "VARCHAR(512)",
        "file_size": "INTEGER",
        "mime_type": "VARCHAR(64)",
        "learning_path_node": "VARCHAR(128)",
        "review_status": "VARCHAR(32)",
        "review_id": "VARCHAR(64)",
        "claim_count": "INTEGER",
        "hallucination_rate": "FLOAT",
        "legacy_reviewer_score": "FLOAT",
        "claim_hallucination_rate": "FLOAT",
        "claim_metric_status": "VARCHAR(32)",
        "difficulty_match": "BOOLEAN",
        "run_id": "VARCHAR(128)",
        "version": "INTEGER NOT NULL DEFAULT 1",
        "parent_resource_id": "VARCHAR(64)",
        "exercise_items": "JSON DEFAULT '[]'",
    }
    with engine.begin() as conn:
        if "generated_resources" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "generated_resources")
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE generated_resources ADD COLUMN {column} {ddl}"))


def _migrate_sqlite_generation_jobs(engine) -> None:
    """为旧版 generation_jobs 补齐异步任务字段。"""
    expected_columns = {
        "request_payload": "JSON DEFAULT '{}'",
        "resource_ids": "JSON DEFAULT '[]'",
        "error_message": "VARCHAR(512)",
        "started_at": "DATETIME",
        "finished_at": "DATETIME",
    }
    with engine.begin() as conn:
        if "generation_jobs" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "generation_jobs")
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE generation_jobs ADD COLUMN {column} {ddl}"))


def _migrate_sqlite_feedback_records(engine) -> None:
    """为旧版 feedback_records 补齐反馈扩展字段。"""
    expected_columns = {
        "feedback_type": "VARCHAR(32)",
        "time_spent_seconds": "INTEGER",
        "completed": "BOOLEAN",
        "self_rating": "INTEGER",
        "practice_result": "JSON DEFAULT '{}'",
        "decision_reason": "VARCHAR(512)",
        "next_action": "VARCHAR(32)",
        "recommended_topics": "JSON DEFAULT '[]'",
        "updated_knowledge_states": "JSON DEFAULT '{}'",
        "regenerate_suggestion": "JSON DEFAULT '{}'",
    }
    with engine.begin() as conn:
        if "feedback_records" not in _sqlite_tables(conn):
            return
        existing = _sqlite_columns(conn, "feedback_records")
        for column, ddl in expected_columns.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE feedback_records ADD COLUMN {column} {ddl}"))
