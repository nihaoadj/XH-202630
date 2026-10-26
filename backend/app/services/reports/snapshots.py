"""Report semantic revisions and bounded process-local snapshot sharing."""
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Condition
import time

from pydantic import BaseModel


def _json_value(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return utc(value).isoformat()
    raise TypeError(f"Unsupported report value: {type(value).__name__}")


def canonical_hash(value) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=_json_value)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def revision_parts(report: dict) -> dict[str, str]:
    # Default coverage is deliberate: new fields participate without requiring a
    # developer to remember an allowlist. Only clock metadata is normalized.
    projection = {key: value for key, value in report.items() if key not in {"report_revision", "generated_at"}}
    projection["freshness"] = {key: value for key, value in projection.get("freshness", {}).items() if key != "source_revisions"}
    projection["window"] = {key: value for key, value in projection.get("window", {}).items() if key not in {"start", "end"}}
    projection["learning_activity"] = {key: value for key, value in projection.get("learning_activity", {}).items() if key not in {"window_start", "window_end"}}
    options = projection.get("generation_options")
    if options is not None:
        options = options.model_dump(mode="json") if isinstance(options, BaseModel) else options
        projection["generation_options"] = {key: value for key, value in options.items() if key != "created_at"}
    groups = {
        "profile": {"learner_id", "profile_version", "as_of_profile_version", "learning_goal", "skill_level", "initial_diagnostic", "report_availability"},
        "mastery": {"ability_nodes", "mastery_summary", "mastery_overview", "mastery_trends", "mastery_trend", "radar", "knowledge_mastery", "weak_points", "strong_points", "weakness_groups", "weakness_priorities", "assessment_conclusions", "diagnostic_measurements", "learning_node_mastery_map", "knowledge_blind_spot_map", "blind_spot_heatmap", "evidence_coverage", "next_resource_focus"},
        "activity": {"learning_activity", "window", "metric_summary"},
        "text_resources": {"resource_credibility_summary", "recent_resource_credibility", "recent_resources", "review_summary"},
        "resource_match": {"resource_difficulty_curve", "resource_difficulty_match", "difficulty_curve"},
        "path": {"current_learning_path", "learning_path", "learning_path_graph", "current_learning_state", "generation_options", "tier_progress"},
        "history": {"feedback_trend", "recent_feedback", "recent_attempts", "feedback_analysis", "recent_feedback_decisions", "recent_knowledge_state_mutations", "recent_followup_runs", "profile_versions", "agent_flow", "next_suggestions"},
    }
    assigned = set().union(*groups.values())
    groups["projection"] = set(projection) - assigned
    return {group: canonical_hash({key: projection[key] for key in sorted(keys) if key in projection}) for group, keys in groups.items()}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def next_boundary(attempt_times, event_times, now: datetime, window_days: int) -> datetime | None:
    """First representable instant at which a half-open window changes."""
    window = timedelta(days=window_days)
    tick = timedelta(microseconds=1)
    boundaries = []
    for stamp in attempt_times:
        stamp = utc(stamp)
        for offset in (timedelta(), window, window * 2):
            try:
                boundary = stamp + offset + tick
            except OverflowError:
                continue  # No representable clock value can cross this edge.
            if boundary > now:
                boundaries.append(boundary)
    for stamp in event_times:
        try:
            boundary = utc(stamp) + window + tick
        except OverflowError:
            continue
        if boundary > now:
            boundaries.append(boundary)
    return min(boundaries, default=None)


class ReportSnapshot:
    """Own the body; callers receive independent copies, metadata stays cheap."""
    __slots__ = ("__body", "__metadata", "computed_at", "valid_until", "size_bytes")

    def __init__(self, body: dict, *, valid_until: datetime | None = None):
        self.__body = deepcopy(body)
        self.__metadata = {key: deepcopy(body.get(key)) for key in ("report_revision", "as_of_profile_version", "data_as_of", "freshness")}
        self.computed_at = utc(body.get("generated_at") or datetime.now(timezone.utc))
        self.valid_until = valid_until
        self.size_bytes = len(json.dumps(body, ensure_ascii=False, default=_json_value).encode("utf-8"))

    def metadata(self) -> dict:
        return deepcopy(self.__metadata)

    def materialize(self) -> dict:
        return deepcopy(self.__body)


@dataclass
class _Entry:
    snapshot: ReportSnapshot
    token: object
    accessed: float


class SnapshotCache:
    def __init__(self, *, capacity=64, max_bytes=32 * 1024 * 1024, idle_seconds=300, wait_seconds=10):
        self.capacity, self.max_bytes = capacity, max_bytes
        self.idle_seconds, self.wait_seconds = idle_seconds, wait_seconds
        self.condition = Condition()
        self.entries = OrderedDict()
        self.inflight = set()
        self.bytes = 0

    def _remove(self, key):
        entry = self.entries.pop(key, None)
        if entry:
            self.bytes -= entry.snapshot.size_bytes

    def discard_learner(self, learner_id):
        with self.condition:
            for key in list(self.entries):
                if key[0] == learner_id:
                    self._remove(key)

    def get(self, key, token, now):
        with self.condition:
            clock = time.monotonic()
            for old_key, entry in list(self.entries.items()):
                if clock - entry.accessed >= self.idle_seconds:
                    self._remove(old_key)
            entry = self.entries.get(key)
            if entry is None:
                return None
            snap = entry.snapshot
            if entry.token != token or now < snap.computed_at or (snap.valid_until is not None and now >= snap.valid_until):
                self._remove(key)
                return None
            entry.accessed = clock
            self.entries.move_to_end(key)
            return snap

    def put(self, key, token, snapshot):
        with self.condition:
            self._remove(key)
            if snapshot.size_bytes > self.max_bytes or self.capacity <= 0:
                return
            self.entries[key] = _Entry(snapshot, token, time.monotonic())
            self.bytes += snapshot.size_bytes
            while len(self.entries) > self.capacity or self.bytes > self.max_bytes:
                self._remove(next(iter(self.entries)))

    def acquire(self, key, *, timeout=None) -> bool:
        with self.condition:
            if key not in self.inflight:
                self.inflight.add(key)
                return True
            budget = self.wait_seconds if timeout is None else max(0, timeout)
            if not self.condition.wait_for(lambda: key not in self.inflight, timeout=budget):
                raise TimeoutError("report snapshot singleflight timed out")
            return False

    def release(self, key):
        with self.condition:
            self.inflight.discard(key)
            self.condition.notify_all()
