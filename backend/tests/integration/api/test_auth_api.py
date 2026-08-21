from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import auth
from app.api.dependencies import get_current_user
from app.db.user.memory import MemoryUserRepository
from app.services.auth_service import AuthService


def _client():
    repository = MemoryUserRepository()
    auth_service = AuthService(repository)
    app = FastAPI()
    app.container = SimpleNamespace(auth_service=lambda: auth_service)
    app.include_router(auth.router, prefix="/api/auth")

    @app.get("/api/private", dependencies=[Depends(get_current_user)])
    def private_route():
        return {"status": "ok"}

    return TestClient(app), repository


def _registration(username: str = "alice") -> dict:
    return {
        "username": username,
        "password": "password123",
        "confirm_password": "password123",
    }


def test_register_requires_only_three_account_fields_and_logs_in():
    client, repository = _client()

    response = client.post("/api/auth/register", json=_registration())

    assert response.status_code == 201
    user = response.json()["user"]
    assert user["username"] == "alice"
    assert user["display_name"] == "alice"
    assert user["identity"] == "其他"
    assert user["education"] == "未填写"
    assert user["major"] == "未填写"
    assert "password" not in response.text
    assert repository._password_hashes[user["user_id"]] != "password123"
    assert client.get("/api/auth/me").status_code == 200
    assert client.get("/api/private").status_code == 200


def test_register_rejects_mismatched_passwords_and_duplicate_username():
    client, _ = _client()
    mismatch = _registration()
    mismatch["confirm_password"] = "different123"

    assert client.post("/api/auth/register", json=mismatch).status_code == 422
    assert client.post("/api/auth/register", json=_registration("MixedCase")).status_code == 201
    duplicate = client.post("/api/auth/register", json=_registration("mixedcase"))
    assert duplicate.status_code == 409


def test_login_logout_and_invalid_password():
    client, _ = _client()
    assert client.post("/api/auth/register", json=_registration()).status_code == 201
    assert client.post("/api/auth/logout").status_code == 200
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/private").status_code == 401

    invalid = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "wrongpass"},
    )
    assert invalid.status_code == 401

    logged_in = client.post(
        "/api/auth/login",
        json={"username": "alice", "password": "password123"},
    )
    assert logged_in.status_code == 200
    assert logged_in.json()["user"]["last_login_at"] is not None
    assert client.get("/api/auth/me").status_code == 200
