import asyncio
import logging

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import main as main_module
from app.config import Settings
from app.core import health as health_module
from app.core.errors import ErrorCode
from app.core.health import ComponentHealth, HealthReport, build_health_report


def make_settings(**overrides):
    values = {"_env_file": None, "embedding_model": "test/model"}
    values.update(overrides)
    return Settings(**values)


def patch_ready_dependencies(monkeypatch):
    ready = lambda: ComponentHealth(status="ready")
    monkeypatch.setattr(health_module, "_check_python", ready)
    monkeypatch.setattr(
        health_module,
        "_check_storage",
        lambda settings, prepare: ComponentHealth(
            status="ready", mode=settings.db_type, ephemeral=False
        ),
    )
    monkeypatch.setattr(health_module, "_check_embedding", lambda settings: ready())
    monkeypatch.setattr(health_module, "_check_vector_store", lambda settings, prepare: ready())
    monkeypatch.setattr(health_module, "_check_resources", lambda settings, prepare: ready())


def test_development_without_key_and_degraded_disabled_is_not_ready(monkeypatch):
    patch_ready_dependencies(monkeypatch)
    report = build_health_report(make_settings(llm_api_key=""))

    assert report.status == "not_ready"
    assert report.llm.code == ErrorCode.CFG_LLM_API_KEY_MISSING.value


def test_demo_without_key_and_explicit_degraded_is_degraded(monkeypatch):
    patch_ready_dependencies(monkeypatch)
    report = build_health_report(make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        llm_api_key="",
    ))

    assert report.status == "degraded"
    assert report.degraded_generation_allowed is True


def test_ready_with_sqlite_and_all_dependencies(monkeypatch):
    patch_ready_dependencies(monkeypatch)
    report = build_health_report(make_settings(llm_api_key="test-key"))

    assert report.status == "ready"
    assert report.storage.mode == "sqlite"


def test_memory_is_ephemeral_and_affects_aggregate(monkeypatch):
    monkeypatch.setattr(health_module, "_check_python", lambda: ComponentHealth(status="ready"))
    monkeypatch.setattr(health_module, "_check_embedding", lambda settings: ComponentHealth(status="ready"))
    monkeypatch.setattr(
        health_module,
        "_check_vector_store",
        lambda settings, prepare: ComponentHealth(status="ready"),
    )
    monkeypatch.setattr(
        health_module,
        "_check_resources",
        lambda settings, prepare: ComponentHealth(status="ready"),
    )
    settings = make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        db_type="memory",
        llm_api_key="test-key",
    )
    report = build_health_report(settings)

    assert report.status == "degraded"
    assert report.storage.ephemeral is True
    assert report.storage.code == ErrorCode.STORAGE_MEMORY_EPHEMERAL.value


def test_sqlite_storage_rejects_unwritable_parent(monkeypatch):
    settings = make_settings(db_type="sqlite")
    monkeypatch.setattr(health_module, "_directory_is_writable", lambda path, prepare: False)

    result = health_module._check_storage(settings, prepare=False)

    assert result.status == "not_ready"
    assert result.code == ErrorCode.STORAGE_SQLITE_PATH_UNWRITABLE.value


@pytest.mark.parametrize(
    ("component", "code"),
    [
        ("embedding", ErrorCode.EMBEDDING_MODEL_UNAVAILABLE),
        ("vector_store", ErrorCode.VECTOR_COLLECTION_EMPTY),
    ],
)
def test_ai_dependency_failure_follows_degraded_policy(monkeypatch, component, code):
    patch_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        health_module,
        f"_check_{component}",
        (lambda settings: ComponentHealth(status="not_ready", code=code.value))
        if component == "embedding"
        else (lambda settings, prepare: ComponentHealth(status="not_ready", code=code.value)),
    )

    strict = build_health_report(make_settings(llm_api_key="test-key"))
    degraded = build_health_report(make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        llm_api_key="test-key",
    ))

    assert strict.status == "not_ready"
    assert degraded.status == "degraded"


def test_unwritable_resource_directory_is_always_not_ready(monkeypatch):
    patch_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        health_module,
        "_check_resources",
        lambda settings, prepare: ComponentHealth(
            status="not_ready", code=ErrorCode.RESOURCE_DIRECTORY_UNWRITABLE.value
        ),
    )
    report = build_health_report(make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        llm_api_key="test-key",
    ))

    assert report.status == "not_ready"


def _http_report(status):
    component = ComponentHealth(status="ready")
    return HealthReport(
        status=status,
        app_mode="demo",
        degraded_generation_allowed=status == "degraded",
        python=component,
        storage=ComponentHealth(status="ready", mode="sqlite", ephemeral=False),
        llm=component,
        embedding=component,
        vector_store=component,
        resources=component,
        error_codes=[],
    )


@pytest.mark.parametrize(
    ("status", "expected_http"),
    [("ready", 200), ("degraded", 200), ("not_ready", 503)],
)
def test_health_http_status_and_secret_redaction(monkeypatch, status, expected_http):
    secret = "health-test-secret"
    settings = make_settings(llm_api_key=secret)
    report = _http_report(status)
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "init_container", lambda: object())
    monkeypatch.setattr(main_module, "init_database", lambda: None)
    monkeypatch.setattr(main_module, "build_health_report", lambda *args, **kwargs: report)

    with TestClient(main_module.app, raise_server_exceptions=False) as client:
        response = client.get("/health")

    assert response.status_code == expected_http
    assert response.json()["status"] == status
    assert secret not in response.text
    assert "traceback" not in response.text.lower()


def test_memory_startup_logs_ephemeral_warning(monkeypatch, caplog):
    settings = make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        db_type="memory",
        llm_api_key="test-key",
    )
    monkeypatch.setattr(main_module, "get_settings", lambda: settings)
    monkeypatch.setattr(main_module, "init_container", lambda: object())
    monkeypatch.setattr(
        main_module,
        "build_health_report",
        lambda *args, **kwargs: _http_report("degraded"),
    )

    with caplog.at_level(logging.WARNING):
        with TestClient(main_module.app):
            pass

    assert "EPHEMERAL STORAGE WARNING" in caplog.text


def test_global_exception_log_does_not_include_raw_secret(caplog):
    secret = "raw-upstream-secret-must-not-appear"
    request = Request({"type": "http", "method": "GET", "path": "/boom", "headers": []})

    with caplog.at_level(logging.ERROR):
        response = asyncio.run(
            main_module.global_exception_handler(request, RuntimeError(secret))
        )

    assert response.status_code == 500
    assert secret not in caplog.text
    assert secret not in response.body.decode("utf-8")
