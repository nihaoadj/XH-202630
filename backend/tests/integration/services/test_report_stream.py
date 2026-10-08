import asyncio
import socket
import threading
import time
from types import SimpleNamespace

import pytest
import httpx
import uvicorn
from fastapi import FastAPI

from app.api.reports.report import stream_report
from app.models.learning_documents.schemas import LearnerProfile


class _Profiles:
    def __init__(self, profile): self.profile = profile
    def get(self, learner_id): return self.profile if learner_id == self.profile.learner_id else None


class _Reports:
    def __init__(self): self.calls = 0
    def build_report(self, profile, *, window_days):
        self.calls += 1
        revision = f"rpt_{('a' if self.calls == 1 else 'b') * 64}"
        return {"report_revision": revision, "as_of_profile_version": 1, "data_as_of": None,
                "freshness": {"source_revisions": {"profile": "one", "mastery": "one", "activity": str(self.calls), "text_resources": "one"}}}


@pytest.mark.asyncio
async def test_report_stream_emits_snapshot_then_safe_changed_domain_only():
    profile = LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件", learning_goal="learn")
    checks = 0
    async def disconnected():
        nonlocal checks
        checks += 1
        return checks > 2
    request = SimpleNamespace(
        headers={}, state=SimpleNamespace(), is_disconnected=disconnected,
        app=SimpleNamespace(container=SimpleNamespace(profile_service=lambda: _Profiles(profile), report_service=lambda: _Reports())),
    )
    response = await stream_report("learner", request, window_days=30)
    chunks = []
    async for chunk in response.body_iterator:
        chunks.append(chunk)
    payload = "".join(chunks)
    assert "event: report_snapshot" in payload
    assert "event: report_changed" in payload
    assert '"changed_domains": ["activity"]' in payload
    assert "Prompt" not in payload and "content_text" not in payload


def test_report_stream_over_real_http_emits_snapshot_then_changed():
    profile = LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件", learning_goal="learn")
    reports = _Reports()
    app = FastAPI()
    app.container = SimpleNamespace(profile_service=lambda: _Profiles(profile), report_service=lambda: reports)
    from app.api.reports.report import router
    app.include_router(router, prefix="/api/report")
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0)); port = probe.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error", access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started
    try:
        with httpx.stream("GET", f"http://127.0.0.1:{port}/api/report/learner/events", timeout=8) as response:
            lines = []
            for line in response.iter_lines():
                if line:
                    lines.append(line)
                if (any("event: report_snapshot" in item for item in lines)
                        and any("event: report_changed" in item for item in lines)
                        and any(item.startswith("data:") and "changed_domains" in item for item in lines)):
                    break
            assert "event: report_snapshot" in lines
            assert "event: report_changed" in lines
            assert any(item.startswith("data:") and "changed_domains" in item for item in lines)
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()
