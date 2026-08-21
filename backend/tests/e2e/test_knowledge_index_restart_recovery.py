from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app import config as config_module
from app import main as main_module
from app.db import database as database_module
from app.db.models import KnowledgeIndexStatusORM


def _ready_report(*_args, **_kwargs):
    return SimpleNamespace(
        status="ready",
        app_mode="development",
        storage=SimpleNamespace(mode="sqlite"),
        error_codes=[],
    )


def _clear_runtime_caches():
    database_module.get_session_factory.cache_clear()
    engine = database_module.get_engine.cache_info()
    if engine.currsize:
        cached_engine = database_module.get_engine()
        if hasattr(cached_engine, "dispose"):
            cached_engine.dispose()
    database_module.get_engine.cache_clear()
    config_module.get_settings.cache_clear()


def test_fastapi_restart_marks_stale_knowledge_index_not_ready(monkeypatch, tmp_path):
    db_path = tmp_path / "knowledge-index-restart.db"
    monkeypatch.setenv("DB_TYPE", "sqlite")
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path.as_posix()}")
    monkeypatch.setenv("RERANK_ENABLED", "false")
    monkeypatch.setenv("KNOWLEDGE_INDEX_STALE_SECONDS", "30")
    monkeypatch.setattr(main_module, "build_health_report", _ready_report)
    _clear_runtime_caches()

    with TestClient(main_module.app):
        container = main_module.app.container
        catalog = container.knowledge_catalog()
        catalog.upsert_knowledge_base({
            "knowledge_base_id": "stale-kb",
            "name": "Stale KB",
            "version": "1.0",
            "learner_levels": [],
            "raw_metadata": {},
        })
        catalog.set_index_status(
            "stale-kb",
            status="indexing",
            active_snapshot_hash="b" * 64,
            expected_chunk_count=4,
            sql_chunk_count=2,
            vector_chunk_count=4,
            smoke_status="not_run",
        )
        with container.db_session_factory()() as db:
            row = db.get(KnowledgeIndexStatusORM, "stale-kb")
            row.updated_at = datetime.now(timezone.utc) - timedelta(minutes=10)
            db.commit()

    with TestClient(main_module.app):
        status = main_module.app.container.knowledge_catalog().get_index_status(
            "stale-kb"
        )

    assert status["status"] == "not_ready"
    assert status["last_error_code"] == "KNOWLEDGE_INDEXING_INTERRUPTED"
    assert status["active_snapshot_hash"] == "b" * 64
    assert status["expected_chunk_count"] == 4
    assert status["sql_chunk_count"] == 2
    assert status["vector_chunk_count"] == 4
    _clear_runtime_caches()
