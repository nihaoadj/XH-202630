"""Production config hardening and credentialed CORS preserve local API use."""

import pytest
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.config import Settings
from app.core.security.cors import cors_options


def production(**overrides):
    values = {
        "_env_file": None, "app_mode": "production", "llm_api_key": "synthetic-no-network",
        "auth_jwt_secret": "synthetic-production-secret-0123456789", "auth_cookie_secure": True,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.mark.parametrize("secret", ["development-only-change-me", "replace-with-a-long-random-secret", "short"])
def test_production_rejects_insecure_secret_without_echo(secret):
    with pytest.raises(ValidationError, match="CFG_PRODUCTION_AUTH_SECRET_INVALID") as caught:
        production(auth_jwt_secret=secret)
    assert secret not in str(caught.value)


def test_production_requires_secure_cookie_and_https_origins():
    with pytest.raises(ValidationError, match="CFG_PRODUCTION_SECURE_COOKIE_REQUIRED"):
        production(auth_cookie_secure=False)
    with pytest.raises(ValidationError, match="CFG_PRODUCTION_CORS_HTTPS_REQUIRED"):
        production(cors_allow_origins=["http://training.example.test"])


@pytest.mark.parametrize("origin", ["*", "https://*.example.test", "https://example.test/path", "https://u:p@example.test", "http://localhost:bad"])
def test_cors_rejects_patterns_and_non_origin_urls(origin):
    with pytest.raises(ValidationError, match="CFG_CORS_ORIGIN_INVALID"):
        Settings(_env_file=None, cors_allow_origins=[origin])


def test_credentialed_cors_only_reflects_allowed_origin():
    app = FastAPI()
    app.add_middleware(CORSMiddleware, **cors_options(production(cors_allow_origins=["https://training.example.test"])))
    client = TestClient(app)
    headers = {"Origin": "https://training.example.test", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"}
    accepted = client.options("/", headers=headers)
    assert accepted.status_code == 200
    assert accepted.headers["access-control-allow-origin"] == headers["Origin"]
    assert accepted.headers["access-control-allow-credentials"] == "true"
    rejected = client.options("/", headers={**headers, "Origin": "https://other.example.test"})
    assert rejected.status_code == 400
    assert "access-control-allow-origin" not in rejected.headers


def test_development_allows_local_dynamic_port_but_not_remote_site():
    options = cors_options(Settings(_env_file=None))
    middleware = CORSMiddleware(FastAPI(), **options)
    assert middleware.is_allowed_origin("http://127.0.0.1:5199")
    assert middleware.is_allowed_origin("http://localhost:5173")
    assert not middleware.is_allowed_origin("http://localhost.attacker.test:5173")
    assert not middleware.is_allowed_origin("https://other.example.test")
