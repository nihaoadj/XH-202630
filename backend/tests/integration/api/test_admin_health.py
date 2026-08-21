from fastapi.testclient import TestClient
from types import SimpleNamespace

from app import main as main_module
from app.api import admin as admin_module
from app.config import Settings
from app.core.health import (
    ComponentHealth,
    HealthReport,
    KnowledgeBaseHealth,
    KnowledgeBaseHealthReport,
)
from app.models.knowledge import IngestionReport


def _runtime_report():
    ready = ComponentHealth(status="ready")
    return HealthReport(
        status="ready",
        app_mode="development",
        degraded_generation_allowed=False,
        python=ready,
        storage=ComponentHealth(status="ready", mode="sqlite", ephemeral=False),
        llm=ready,
        embedding=ready,
        vector_store=ready,
        resources=ready,
        error_codes=[],
    )


def _admin_report():
    return KnowledgeBaseHealthReport(
        status="degraded",
        default_knowledge_base_id="default_kb",
        knowledge_bases=[
            KnowledgeBaseHealth(
                knowledge_base_id="default_kb",
                is_default=True,
                status="ready",
                collection_name="kb_default",
                collection_state="populated",
                count=3,
            ),
            KnowledgeBaseHealth(
                knowledge_base_id="optional_kb",
                status="not_ready",
                code="VECTOR_COLLECTION_MISSING",
                collection_name="kb_optional",
                collection_state="missing",
            ),
        ],
        error_codes=["VECTOR_COLLECTION_MISSING"],
    )


def _client(monkeypatch, token):
    settings = Settings(
        _env_file=None,
        admin_health_token=token,
        llm_api_key="test-key",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    catalog = SimpleNamespace(get_index_status=lambda knowledge_base_id: None)
    ingestion = SimpleNamespace(
        reconcile=lambda knowledge_base_id: IngestionReport(
            knowledge_base_id=knowledge_base_id,
            status="ready",
            index_schema_version="1.0",
            active_snapshot_hash="a" * 64,
            document_count=1,
            expected_active_chunk_count=1,
            sql_active_chunk_count=1,
            vector_chunk_count=1,
            smoke_status="passed",
        )
    )
    container = SimpleNamespace(
        knowledge_catalog=lambda: catalog,
        ingestion_service=lambda: ingestion,
    )
    monkeypatch.setattr(main_module, "init_container", lambda: container)
    monkeypatch.setattr(main_module, "init_database", lambda: None)
    monkeypatch.setattr(main_module, "build_health_report", lambda *args, **kwargs: _runtime_report())
    monkeypatch.setattr(admin_module, "get_settings", lambda: settings)
    monkeypatch.setattr(
        admin_module,
        "build_knowledge_base_health_report",
        lambda settings, **kwargs: _admin_report(),
    )
    return TestClient(main_module.app, raise_server_exceptions=False)


def test_admin_kb_health_is_disabled_without_configured_token(monkeypatch):
    with _client(monkeypatch, "") as client:
        response = client.get("/api/admin/knowledge-bases/health")

    assert response.status_code == 404
    assert response.json()["code"] == "ADMIN_HEALTH_DISABLED"


def test_admin_kb_health_rejects_invalid_token(monkeypatch):
    with _client(monkeypatch, "expected-token") as client:
        response = client.get(
            "/api/admin/knowledge-bases/health",
            headers={"X-Admin-Token": "wrong-token"},
        )

    assert response.status_code == 401
    assert response.json()["code"] == "ADMIN_UNAUTHORIZED"
    assert "expected-token" not in response.text


def test_partial_kb_failure_returns_degraded_http_200_to_admin(monkeypatch):
    with _client(monkeypatch, "expected-token") as client:
        response = client.get(
            "/api/admin/knowledge-bases/health",
            headers={"X-Admin-Token": "expected-token"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "degraded"
    assert response.json()["knowledge_bases"][0]["is_default"] is True
    assert response.json()["knowledge_bases"][1]["status"] == "not_ready"
    assert "expected-token" not in response.text


def test_admin_can_explicitly_reconcile_one_knowledge_base(monkeypatch):
    with _client(monkeypatch, "expected-token") as client:
        response = client.post(
            "/api/admin/knowledge-bases/default_kb/reconcile",
            headers={"X-Admin-Token": "expected-token"},
        )

    assert response.status_code == 200
    assert response.json()["knowledge_base_id"] == "default_kb"
    assert response.json()["status"] == "ready"
    assert response.json()["sql_active_chunk_count"] == 1
    assert response.json()["vector_chunk_count"] == 1


def test_admin_reconcile_requires_token(monkeypatch):
    with _client(monkeypatch, "expected-token") as client:
        response = client.post(
            "/api/admin/knowledge-bases/default_kb/reconcile",
        )

    assert response.status_code == 401
    assert response.json()["code"] == "ADMIN_UNAUTHORIZED"
