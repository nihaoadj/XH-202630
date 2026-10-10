"""Slow synchronous report/courseware reads must leave the event loop available."""

import asyncio
import threading
from time import monotonic
from types import SimpleNamespace

import pytest

from app.api.courseware import courseware
from app.api.reports import report


class RequestStub:
    headers = {}

    def __init__(self, container):
        self.app = SimpleNamespace(container=container)

    async def is_disconnected(self):
        return False


async def _assert_available(iterator, entered, release):
    started = monotonic()
    pending = asyncio.create_task(anext(iterator))
    try:
        assert await asyncio.to_thread(entered.wait, 2)
        # Under the old code the reader blocks the loop for the 3s timeout.
        assert monotonic() - started < 1.5
        await asyncio.wait_for(asyncio.sleep(0), timeout=0.5)
    finally:
        release.set()
    event = await asyncio.wait_for(pending, timeout=2)
    await iterator.aclose()
    return event


@pytest.mark.asyncio
async def test_report_stream_runs_blocking_snapshot_in_worker(monkeypatch):
    entered, release = threading.Event(), threading.Event()

    def build_report(profile, *, window_days):
        entered.set()
        release.wait(3)
        return {"report_revision": "rpt_test", "freshness": {"source_revisions": {}}, "as_of_profile_version": 1, "data_as_of": "synthetic"}

    profile = SimpleNamespace(learner_id="learner")
    service = SimpleNamespace(build_report=build_report)
    request = RequestStub(SimpleNamespace(profile_service=lambda: SimpleNamespace(get=lambda _: profile)))
    monkeypatch.setattr(report, "_profile_and_service", lambda *_: (profile, service))
    response = await report.stream_report("learner", request, window_days=30)
    event = await _assert_available(response.body_iterator, entered, release)
    assert "event: report_snapshot" in event


@pytest.mark.asyncio
async def test_courseware_stream_runs_blocking_queries_in_worker(monkeypatch):
    entered, release = threading.Event(), threading.Event()
    job = SimpleNamespace(status="published")

    def events(run_id, sequence):
        entered.set()
        release.wait(3)
        return [{"event_sequence": 1, "run_id": run_id}]

    service = SimpleNamespace(events=events, get_job=lambda _: job)
    request = RequestStub(SimpleNamespace(courseware_service=lambda: service))
    monkeypatch.setattr(courseware, "_authorized_job", lambda *_: job)
    response = courseware.stream_courseware_events("run", request)
    event = await _assert_available(response.body_iterator, entered, release)
    assert "event: courseware_progress" in event and '"run_id":"run"' in event
