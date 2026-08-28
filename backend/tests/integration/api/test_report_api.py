from types import SimpleNamespace

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app.api.reports import report as report_routes
from app.api.dependencies import get_current_user
from app.db.feedback.memory import MemoryFeedbackRepository
from app.db.learners.memory import MemoryLearnerRepository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService
from app.services.reports.reports import ReportSnapshotUnstable
from app.models.users.users import UserProfile


def _client():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(
        learner_id="report-learner", learner_type="test", education="本科", major="软件",
        learning_goal="report",
    ))
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners),
        report_service=lambda: ReportService(MemoryResourceRepository(), MemoryFeedbackRepository()),
    )
    app.include_router(report_routes.router, prefix="/api/report")
    return TestClient(app)


def test_report_uses_window_specific_etag_and_safe_conditional_parsing():
    client = _client()
    current = client.get("/api/report/report-learner?window_days=30")
    other_window = client.get("/api/report/report-learner?window_days=7")
    assert current.status_code == 200
    assert current.headers["cache-control"] == "private, no-cache"
    assert current.headers["etag"] != other_window.headers["etag"]
    assert client.get("/api/report/report-learner", headers={"If-None-Match": f'W/{current.headers["etag"]}, "other"'}).status_code == 304
    assert client.get("/api/report/report-learner", headers={"If-None-Match": '"not-a-report-etag"'}).status_code == 200


def test_report_rejects_invalid_stream_and_pagination_cursors():
    client = _client()
    stream = client.get("/api/report/report-learner/events?after_revision=bad")
    assert stream.status_code == 400
    assert stream.json()["detail"]["code"] == "REPORT_STREAM_CURSOR_INVALID"
    page = client.get("/api/report/report-learner/resource-credibility?cursor=bad")
    assert page.status_code == 400
    assert page.json()["detail"]["code"] == "REPORT_CURSOR_INVALID"


def test_report_returns_safe_503_when_snapshot_keeps_changing():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(learner_id="report-learner", learner_type="test", education="本科", major="软件", learning_goal="report"))
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners),
        report_service=lambda: SimpleNamespace(build_report=lambda *_args, **_kwargs: (_ for _ in ()).throw(ReportSnapshotUnstable())),
    )
    app.include_router(report_routes.router, prefix="/api/report")
    response = TestClient(app).get("/api/report/report-learner")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "REPORT_SNAPSHOT_UNSTABLE"


def test_private_report_route_rejects_missing_and_cross_user_access():
    learners = MemoryLearnerRepository()
    learners.save(LearnerProfile(learner_id="report-learner", user_id="owner", learner_type="test", education="本科", major="软件", learning_goal="report"))
    owner = UserProfile(user_id="owner", display_name="Owner", identity="测试", education="本科", major="软件")
    other = owner.model_copy(update={"user_id": "other"})
    app = FastAPI()
    app.container = SimpleNamespace(
        profile_service=lambda: ProfileService(learners), report_service=lambda: ReportService(MemoryResourceRepository(), MemoryFeedbackRepository()),
        auth_service=lambda: SimpleNamespace(resolve_token=lambda token: owner if token == "owner-token" else other if token == "other-token" else None),
    )
    app.include_router(report_routes.router, prefix="/api/report", dependencies=[Depends(get_current_user)])
    client = TestClient(app)
    assert client.get("/api/report/report-learner").status_code == 401
    # Set cookies on the client so Starlette does not emit its deprecated
    # per-request ``cookies=...`` warning and persistence is explicit.
    client.cookies.set("training_pilot_token", "owner-token")
    assert client.get("/api/report/report-learner").status_code == 200
    client.cookies.set("training_pilot_token", "other-token")
    assert client.get("/api/report/report-learner").status_code == 404
