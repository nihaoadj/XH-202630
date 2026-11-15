from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from app.services.reports.snapshots import ReportSnapshot, SnapshotCache, next_boundary, revision_parts

NOW = datetime(2026, 10, 23, tzinfo=timezone.utc)


def _body():
    return {"generated_at": NOW, "report_revision": "rpt_a", "freshness": {"source_revisions": {}, "warnings": []},
            "window": {"start": NOW, "end": NOW, "window_days": 7},
            "learning_activity": {"window_start": NOW, "window_end": NOW, "verified_attempt_count": 1},
            "generation_options": {"created_at": NOW, "tier_progress": {"updated_at": NOW}},
            "recent_feedback": [{"message": "first"}]}


def test_semantic_revision_normalizes_only_computation_metadata_and_covers_new_fields():
    body = _body()
    changed = deepcopy(body)
    later = NOW + timedelta(seconds=1)
    changed["generated_at"] = later
    changed["window"].update(start=later, end=later)
    changed["learning_activity"].update(window_start=later, window_end=later)
    changed["generation_options"]["created_at"] = later
    changed["report_revision"] = "other"
    changed["freshness"]["source_revisions"] = {"self": "reference"}
    assert revision_parts(body) == revision_parts(changed)
    changed["generation_options"]["tier_progress"]["updated_at"] = later
    assert revision_parts(body)["path"] != revision_parts(changed)["path"]
    changed = deepcopy(body)
    changed["recent_feedback"][0]["message"] = "corrected"
    assert revision_parts(body)["history"] != revision_parts(changed)["history"]
    changed = deepcopy(body)
    changed["future_field"] = {"fact": True}
    assert revision_parts(body)["projection"] != revision_parts(changed)["projection"]
    changed = deepcopy(body)
    changed["freshness"]["warnings"] = ["UNAVAILABLE"]
    assert revision_parts(body) != revision_parts(changed)


@pytest.mark.parametrize("days", [7, 30, 90])
def test_half_open_window_boundaries_include_future_entry_current_exit_and_previous_exit(days):
    window = timedelta(days=days)
    tick = timedelta(microseconds=1)
    assert next_boundary([NOW], [], NOW, days) == NOW + tick
    assert next_boundary([NOW - window], [], NOW, days) == NOW + tick
    assert next_boundary([NOW - window * 2], [], NOW, days) == NOW + tick
    assert next_boundary([NOW - window * 2 - tick], [], NOW, days) is None
    assert next_boundary([], [NOW - window], NOW, days) == NOW + tick
    assert next_boundary([datetime.max.replace(tzinfo=timezone.utc)], [], NOW, days) is None


def test_snapshot_owns_body_and_metadata():
    original = _body()
    snapshot = ReportSnapshot(original)
    original["recent_feedback"][0]["message"] = "outside"
    snapshot.materialize()["recent_feedback"][0]["message"] = "caller"
    snapshot.metadata()["freshness"]["warnings"].append("caller")
    assert snapshot.materialize()["recent_feedback"][0]["message"] == "first"
    assert snapshot.metadata()["freshness"]["warnings"] == []


def test_cache_capacity_size_idle_time_and_boundary_are_bounded(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr("app.services.reports.snapshots.time.monotonic", lambda: clock[0])
    snapshot = ReportSnapshot(_body(), valid_until=NOW + timedelta(seconds=5))
    cache = SnapshotCache(capacity=2, max_bytes=snapshot.size_bytes * 2, idle_seconds=10, wait_seconds=0)
    keys = [("learner", str(i)) for i in range(3)]
    for key in keys:
        cache.put(key, "epoch", snapshot)
    assert len(cache.entries) == 2 and cache.bytes == snapshot.size_bytes * 2
    assert cache.get(keys[0], "epoch", NOW) is None
    assert cache.get(keys[1], "epoch", NOW) is snapshot
    assert cache.get(keys[1], "changed", NOW) is None
    assert cache.get(keys[2], "epoch", NOW + timedelta(seconds=5)) is None
    cache.put(keys[0], "epoch", snapshot)
    assert cache.get(keys[0], "epoch", NOW - timedelta(microseconds=1)) is None
    cache.put(keys[0], "epoch", snapshot)
    clock[0] = 10
    assert cache.get(keys[0], "epoch", NOW) is None
    cache.max_bytes = snapshot.size_bytes - 1
    cache.put(keys[0], "epoch", snapshot)
    assert not cache.entries and cache.bytes == 0
    assert cache.acquire(keys[0])
    with pytest.raises(TimeoutError):
        cache.acquire(keys[0])
    cache.release(keys[0])
