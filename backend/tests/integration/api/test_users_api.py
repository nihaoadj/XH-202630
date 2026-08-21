from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import users
from app.db.user.memory import MemoryUserRepository
from app.services.user_service import UserService


def _client():
    user_service = UserService(MemoryUserRepository())
    app = FastAPI()
    app.container = SimpleNamespace(user_service=lambda: user_service)
    app.include_router(users.router, prefix="/api/users")
    return TestClient(app)


def test_create_user_generates_hidden_user_id():
    client = _client()

    response = client.post(
        "/api/users/",
        json={
            "display_name": "测试用户",
            "identity": "在校学生",
            "education": "本科",
            "major": "软件工程",
            "job_role": "学生",
            "experience_years": 1,
            "metadata": {},
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["user_id"].startswith("user_")
    assert body["display_name"] == "测试用户"
    assert body["identity"] == "在校学生"
