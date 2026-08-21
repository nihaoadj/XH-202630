import pytest
from pydantic import ValidationError

from app.config import Settings
from app.containers import Container
from app.db import database as database_module


def make_settings(**overrides):
    values = {"_env_file": None}
    values.update(overrides)
    return Settings(**values)


def test_settings_safe_defaults():
    settings = make_settings()

    assert settings.app_mode == "development"
    assert settings.allow_degraded_generation is False
    assert settings.db_type == "sqlite"
    assert settings.debug is False
    assert settings.sql_echo is False
    assert settings.llm_workflow_timeout_seconds == 1200
    assert settings.workflow_run_lease_seconds == 1260


def test_settings_treats_an_empty_optional_proxy_as_direct_access():
    assert make_settings(llm_proxy_url="  ").llm_proxy_url is None


def test_container_gives_resource_agents_their_dedicated_recovery_budget():
    settings = make_settings()
    container = Container()
    container.config.from_dict(settings.model_dump(mode="python"))

    gateway = container.llm_gateway()

    assert gateway.options_for("text_resource_agent").max_attempts == 2
    assert gateway.options_for("assessment_agent").max_attempts == 2
    assert gateway.options_for("html_practice_guide_html").max_attempts == 2
    assert gateway.options_for("reviewer").max_attempts == 2


@pytest.mark.parametrize("mode", ["development", "demo", "production"])
def test_settings_accept_legal_app_modes(mode):
    overrides = {"app_mode": mode}
    if mode == "production":
        overrides["llm_api_key"] = "test-production-key"
    assert make_settings(**overrides).app_mode == mode


@pytest.mark.parametrize("db_type", ["memory", "sqlite", "postgresql"])
def test_settings_accept_legal_db_types(db_type):
    database_url = (
        "postgresql://localhost/test"
        if db_type == "postgresql"
        else "sqlite:///./data/domain_knowledge.db"
    )
    assert make_settings(db_type=db_type, database_url=database_url).db_type == db_type


def test_settings_reject_invalid_app_mode_without_echoing_input():
    invalid_value = "invalid-mode-sensitive-value"
    with pytest.raises(ValidationError) as caught:
        make_settings(app_mode=invalid_value)

    message = str(caught.value)
    assert "CFG_INVALID_APP_MODE" in message
    assert invalid_value not in message


def test_settings_reject_invalid_db_type():
    with pytest.raises(ValidationError, match="CFG_INVALID_DB_TYPE"):
        make_settings(db_type="redis")


def test_settings_reject_database_url_mismatch():
    with pytest.raises(ValidationError, match="CFG_DATABASE_URL_MISMATCH"):
        make_settings(db_type="sqlite", database_url="postgresql://db/test")


@pytest.mark.parametrize("api_key", ["", "your_api_key_here", "changeme", "replace_me"])
def test_production_rejects_missing_or_placeholder_key(api_key):
    expected = "CFG_LLM_API_KEY_MISSING" if not api_key else "CFG_LLM_API_KEY_PLACEHOLDER"
    with pytest.raises(ValidationError, match=expected):
        make_settings(app_mode="production", llm_api_key=api_key)


def test_production_rejects_degraded_and_memory():
    with pytest.raises(ValidationError, match="CFG_PRODUCTION_DEGRADED_FORBIDDEN"):
        make_settings(
            app_mode="production",
            allow_degraded_generation=True,
            llm_api_key="test-key",
        )
    with pytest.raises(ValidationError, match="CFG_PRODUCTION_EPHEMERAL_STORAGE"):
        make_settings(
            app_mode="production",
            db_type="memory",
            llm_api_key="test-key",
        )


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("llm_base_url", "not-a-url", "CFG_LLM_ENDPOINT_INVALID"),
        ("llm_model", "", "CFG_LLM_MODEL_MISSING"),
        ("embedding_model", "", "CFG_EMBEDDING_MODEL_MISSING"),
    ],
)
def test_production_rejects_incomplete_model_configuration(field, value, code):
    overrides = {"app_mode": "production", "llm_api_key": "test-key", field: value}
    with pytest.raises(ValidationError, match=code):
        make_settings(**overrides)


def test_demo_allows_explicit_degraded_mode_without_key():
    settings = make_settings(
        app_mode="demo",
        allow_degraded_generation=True,
        llm_api_key="",
    )
    assert settings.allow_degraded_generation is True


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retrieval_top_k_default", 0),
        ("retrieval_max_queries", 11),
        ("retrieval_max_evidence", 21),
        ("retrieval_min_evidence", 0),
        ("retrieval_min_normalized_score", 1.1),
        ("evidence_max_excerpt_chars", 99),
        ("vector_distance_metric", "l2"),
    ],
)
def test_retrieval_policy_rejects_unsafe_values_with_stable_code(field, value):
    with pytest.raises(ValidationError, match="CFG_INVALID_RETRIEVAL_POLICY"):
        make_settings(**{field: value})


def test_retrieval_min_evidence_cannot_exceed_maximum():
    with pytest.raises(ValidationError, match="CFG_INVALID_RETRIEVAL_POLICY"):
        make_settings(retrieval_min_evidence=4, retrieval_max_evidence=3)


@pytest.mark.parametrize(
    ("overrides", "code"),
    [
        ({"llm_request_timeout_seconds": 0}, "CFG_INVALID_LLM_TIMEOUT"),
        (
            {
                "llm_request_timeout_seconds": 30,
                "llm_workflow_timeout_seconds": 30,
            },
            "CFG_INVALID_LLM_TIMEOUT",
        ),
        ({"llm_max_attempts": 4}, "CFG_INVALID_LLM_RETRY_POLICY"),
        (
            {"llm_resource_generation_max_attempts": 4},
            "CFG_INVALID_LLM_RETRY_POLICY",
        ),
        (
            {
                "llm_retry_base_delay_seconds": 4,
                "llm_retry_max_delay_seconds": 3,
            },
            "CFG_INVALID_LLM_RETRY_POLICY",
        ),
        ({"llm_max_output_tokens": 100}, "CFG_INVALID_LLM_TOKEN_LIMIT"),
        (
            {"llm_structured_output_mode": "unknown"},
            "CFG_INVALID_LLM_STRUCTURED_OUTPUT_MODE",
        ),
    ],
)
def test_settings_reject_invalid_llm_runtime_budget(overrides, code):
    with pytest.raises(ValidationError, match=code):
        make_settings(**overrides)


def test_legacy_chroma_collection_name_is_a_prefix_during_compatibility_window():
    legacy = make_settings(chroma_collection_name="legacy_collection")
    preferred = make_settings(
        chroma_collection_name="legacy_collection",
        chroma_collection_prefix="preferred",
    )
    explicit_default = make_settings(
        chroma_collection_name="legacy_collection",
        chroma_collection_prefix="kb",
    )

    assert legacy.chroma_collection_prefix == "legacy_collection"
    assert preferred.chroma_collection_prefix == "preferred"
    assert explicit_default.chroma_collection_prefix == "kb"


def test_api_key_is_secret_in_repr_and_dump():
    secret = "test-key-must-not-leak"
    settings = make_settings(llm_api_key=secret)

    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())


def test_admin_health_token_is_secret_in_repr_and_dump():
    secret = "admin-health-token-must-not-leak"
    settings = make_settings(admin_health_token=secret)

    assert secret not in repr(settings)
    assert secret not in str(settings.model_dump())


def test_debug_does_not_enable_sql_echo(monkeypatch, tmp_path):
    captured = {}
    settings = make_settings(
        debug=True,
        sql_echo=False,
        database_url=f"sqlite:///{(tmp_path / 'test.db').as_posix()}",
    )

    def fake_create_engine(url, **kwargs):
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(database_module, "get_settings", lambda: settings)
    monkeypatch.setattr(database_module, "create_engine", fake_create_engine)
    database_module.get_engine()

    assert captured["echo"] is False
    assert captured["hide_parameters"] is True
