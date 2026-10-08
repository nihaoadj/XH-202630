from sqlalchemy import inspect

from app import config as config_module
from app.db.shared import database as database_module


def _clear_database_caches() -> None:
    database_module.get_session_factory.cache_clear()
    if database_module.get_engine.cache_info().currsize:
        engine = database_module.get_engine()
        if hasattr(engine, "dispose"):
            engine.dispose()
    database_module.get_engine.cache_clear()
    config_module.get_settings.cache_clear()


def test_fresh_sqlite_initialization_runs_all_migrations(tmp_path, monkeypatch):
    database_path = tmp_path / "fresh.db"
    monkeypatch.setenv("APP_MODE", "development")
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{database_path.as_posix()}")

    _clear_database_caches()
    try:
        database_module.init_database()
        engine = database_module.get_engine()
        tables = set(inspect(engine).get_table_names())
    finally:
        _clear_database_caches()

    assert {
        "diagnostic_questions",
        "feedback_followup_runs",
        "knowledge_chunk_skill_node_mappings",
    } <= tables
