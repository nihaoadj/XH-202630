"""Small repository with memory and SQL implementations for courseware."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
from threading import Lock
from typing import Any, Callable

from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.courseware.models import (
    CoursewareArtifactORM,
    CoursewareEventORM,
    CoursewareGenerationJobORM,
    CoursewareReviewORM,
    CoursewareResourceORM,
    CoursewareSceneORM,
    CoursewareSceneRevisionORM,
    CoursewareOutboxORM,
    CoursewareWorkflowCheckpointORM,
    CoursewareReleaseORM,
    CoursewareSourceLinkORM,
    CoursewareSpecORM,
    CoursewareLearningEventORM,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _error_parts(error: dict[str, Any] | Exception) -> tuple[str, str]:
    if isinstance(error, dict):
        return str(error.get("code") or "TASK_FAILED"), str(error.get("message") or "课件任务失败")
    return type(error).__name__, str(error)[:512] or "课件任务失败"


def _retry_at(attempt: int, salt: str = "") -> datetime:
    """Bound retry delay with stable per-task jitter for reproducible retries."""
    base = min(300, 2 ** max(0, min(attempt, 8) - 1))
    digest = hashlib.sha256(f"{salt}:{attempt}".encode()).digest()
    jitter = int.from_bytes(digest[:2], "big") / 65535
    return _now() + timedelta(seconds=base + jitter)


def _job_row(row: CoursewareGenerationJobORM) -> dict[str, Any]:
    return {
        "run_id": row.run_id, "learner_id": row.learner_id,
        "knowledge_base_id": row.knowledge_base_id, "title": row.title,
        "publish_mode": row.publish_mode,
        "source_resource_ids": row.source_resource_ids or [],
        "request_options": row.request_options or {},
        "source_snapshots": row.source_snapshots or [], "request_hash": row.request_hash,
        "idempotency_key": row.idempotency_key, "status": row.status,
        "warnings": row.warnings or [], "error_code": row.error_code,
        "error_message": row.error_message, "resource_id": row.resource_id,
        "attempt": row.attempt or 0, "release_policy": row.release_policy,
        "next_event_sequence": row.next_event_sequence or 1, "deadline_at": row.deadline_at,
        "cancel_requested_at": row.cancel_requested_at, "released_release_id": row.released_release_id,
        "created_at": row.created_at, "updated_at": row.updated_at,
    }


def _resource_row(row: CoursewareResourceORM) -> dict[str, Any]:
    return {
        "resource_id": row.resource_id, "resource_family_id": row.resource_family_id,
        "run_id": row.run_id, "learner_id": row.learner_id,
        "knowledge_base_id": row.knowledge_base_id, "title": row.title, "topic": row.topic,
        "status": row.status, "version": row.version, "file_path": row.file_path,
        "file_size": row.file_size, "artifact_sha256": row.artifact_sha256,
        "renderer_version": row.renderer_version, "runtime_version": row.runtime_version,
        "source_summary": row.source_summary or [], "warnings": row.warnings or [],
        "created_at": row.created_at, "published_at": row.published_at,
        "released_release_id": row.released_release_id,
    }


def _outbox_row(row: CoursewareOutboxORM | dict[str, Any]) -> dict[str, Any]:
    if isinstance(row, dict):
        return deepcopy(row)
    return {"outbox_id": row.outbox_id, "run_id": row.run_id, "scene_id": row.scene_id,
            "event_type": row.event_type, "task_kind": row.task_kind, "status": row.status,
            "claimed_by": row.claimed_by, "lease_expires_at": row.lease_expires_at,
            "attempt": row.attempt, "max_attempts": row.max_attempts,
            "next_attempt_at": row.next_attempt_at, "last_error_code": row.last_error_code,
            "last_error_message": row.last_error_message, "dead_lettered_at": row.dead_lettered_at,
            "payload": row.payload or {}, "idempotency_key": row.idempotency_key,
            "delivered_at": row.delivered_at, "created_at": row.created_at}


class MemoryCoursewareRepository:
    def __init__(self) -> None:
        self.jobs: dict[str, dict[str, Any]] = {}
        self.jobs_by_request: dict[tuple[str, str], str] = {}
        self.resources: dict[str, dict[str, Any]] = {}
        self.links: dict[str, list[dict[str, Any]]] = {}
        self.specs: dict[str, dict[str, Any]] = {}
        self.scenes: dict[str, dict[str, Any]] = {}
        self.reviews: dict[str, dict[str, Any]] = {}
        self.events: dict[str, list[dict[str, Any]]] = {}
        self.artifacts: dict[str, dict[str, Any]] = {}
        self.scene_revisions: dict[str, list[dict[str, Any]]] = {}
        self.outbox: dict[str, dict[str, Any]] = {}
        self.checkpoints: dict[tuple[str, str, int], dict[str, Any]] = {}
        self.releases: dict[str, dict[str, Any]] = {}
        self.learning_events: dict[str, dict[str, Any]] = {}
        self._learning_sequence = 0
        self._scene_claim_lock = Lock()

    def create_job(self, row: dict[str, Any]) -> dict[str, Any]:
        key = (row["learner_id"], row["request_hash"])
        prior = self.jobs_by_request.get(key)
        if prior:
            return deepcopy(self.jobs[prior])
        now = _now()
        stored = deepcopy({**row, "created_at": now, "updated_at": now, "warnings": []})
        self.jobs[row["run_id"]] = stored
        self.jobs_by_request[key] = row["run_id"]
        return deepcopy(stored)

    def create_job_with_task_once(self, row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        stored = self.create_job(row)
        # Idempotent requests return the existing run; the outbox must point
        # at that run rather than the newly generated (discarded) UUID.
        task = {**task, "run_id": stored["run_id"],
                "outbox_id": f"cwo_{stored['run_id']}",
                "idempotency_key": f"courseware.run:{stored['run_id']}"}
        self.enqueue_task_once(task)
        self.append_event_once(stored["run_id"], f"{stored['run_id']}:queued", "job", "queued")
        return stored

    def get_job(self, run_id: str) -> dict[str, Any] | None:
        row = self.jobs.get(run_id)
        return deepcopy(row) if row else None

    def update_job(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        row = self.jobs.get(run_id)
        if row is None:
            return None
        row.update(deepcopy(changes))
        row["updated_at"] = _now()
        return deepcopy(row)

    def save_resource(self, row: dict[str, Any], links: list[dict[str, Any]]) -> dict[str, Any]:
        existing = self.resources.get(row["resource_id"])
        if existing:
            return deepcopy(existing)
        stored = deepcopy({**row, "created_at": _now(), "published_at": _now()})
        self.resources[row["resource_id"]] = stored
        self.links[row["resource_id"]] = deepcopy(links)
        return deepcopy(stored)

    def update_resource_status(self, resource_id: str, status: str) -> dict[str, Any] | None:
        row = self.resources.get(resource_id)
        if row is None:
            return None
        row["status"] = status
        return deepcopy(row)

    def update_resource_artifact(self, resource_id: str, **changes: Any) -> dict[str, Any] | None:
        row = self.resources.get(resource_id)
        if row is None:
            return None
        row.update(deepcopy(changes))
        return deepcopy(row)

    def get_resource(self, resource_id: str) -> dict[str, Any] | None:
        row = self.resources.get(resource_id)
        return deepcopy(row) if row else None

    def get_resource_by_run(self, run_id: str) -> dict[str, Any] | None:
        row = next((item for item in self.resources.values() if item["run_id"] == run_id), None)
        return deepcopy(row) if row else None

    def list_resources(self, learner_id: str) -> list[dict[str, Any]]:
        return sorted(
            (deepcopy(row) for row in self.resources.values() if row["learner_id"] == learner_id),
            key=lambda item: item.get("published_at") or _now(), reverse=True,
        )

    def get_links(self, resource_id: str) -> list[dict[str, Any]]:
        return deepcopy(self.links.get(resource_id, []))

    def save_spec(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy({**row, "created_at": _now()})
        self.specs[row["spec_id"]] = stored
        return deepcopy(stored)

    def get_spec_by_run(self, run_id: str) -> dict[str, Any] | None:
        row = next((value for value in self.specs.values() if value["run_id"] == run_id), None)
        return deepcopy(row) if row else None

    def upsert_scene(self, row: dict[str, Any]) -> dict[str, Any]:
        now = _now()
        previous = self.scenes.get(row["scene_id"], {})
        stored = deepcopy({**previous, **row, "created_at": previous.get("created_at", now), "updated_at": now})
        self.scenes[row["scene_id"]] = stored
        return deepcopy(stored)

    def get_scene(self, scene_id: str) -> dict[str, Any] | None:
        row = self.scenes.get(scene_id)
        return deepcopy(row) if row else None

    def claim_scene(self, scene_id: str, owner: str, lease_seconds: int = 120) -> dict[str, Any] | None:
        with self._scene_claim_lock:
            row = self.scenes.get(scene_id)
            now = _now()
            if row is None or (row.get("lease_expires_at") and row["lease_expires_at"] > now):
                return None
            row.update({"lease_owner": owner, "lease_expires_at": now + timedelta(seconds=lease_seconds)})
            return deepcopy(row)

    def list_scenes(self, spec_id: str) -> list[dict[str, Any]]:
        rows = (deepcopy(row) for row in self.scenes.values() if row["spec_id"] == spec_id)
        return sorted(rows, key=lambda row: row["scene_order"])

    def save_scene_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy({**row, "created_at": _now()})
        self.scene_revisions.setdefault(row["scene_id"], []).append(stored)
        return deepcopy(stored)

    def list_scene_revisions(self, scene_id: str) -> list[dict[str, Any]]:
        return deepcopy(self.scene_revisions.get(scene_id, []))

    def enqueue_outbox(self, row: dict[str, Any]) -> dict[str, Any]:
        existing = next((item for item in self.outbox.values() if item["idempotency_key"] == row["idempotency_key"]), None)
        if existing:
            return deepcopy(existing)
        stored = deepcopy({"task_kind": "courseware.scene.revise", "status": "queued", "attempt": 0,
                           "max_attempts": 3, "next_attempt_at": None, "claimed_by": None,
                           "lease_expires_at": None, "last_error_code": None, "last_error_message": None,
                           "dead_lettered_at": None, **row, "created_at": _now(), "delivered_at": None})
        self.outbox[row["outbox_id"]] = stored
        return deepcopy(stored)

    def enqueue_task_once(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.enqueue_outbox({"task_kind": "courseware.run", "status": "queued", "attempt": 0,
                                    "max_attempts": 3, **row})

    def claim_task_batch(self, owner: str, now: datetime | None = None, limit: int = 10,
                         lease_seconds: int = 120) -> list[dict[str, Any]]:
        now = now or _now()
        claimed = []
        for row in sorted(self.outbox.values(), key=lambda item: item.get("created_at") or now):
            if len(claimed) >= limit or row.get("delivered_at") or row.get("status") in {"complete", "dead_lettered"}:
                continue
            if row.get("status") == "claimed" and not (row.get("lease_expires_at") and row["lease_expires_at"] <= now):
                continue
            if row.get("status") not in {"queued", "retry", "claimed"}:
                continue
            if row.get("next_attempt_at") and row["next_attempt_at"] > now:
                continue
            if row.get("lease_expires_at") and row["lease_expires_at"] > now:
                continue
            row.update({"status": "claimed", "claimed_by": owner, "lease_expires_at": now + timedelta(seconds=lease_seconds),
                        "attempt": int(row.get("attempt") or 0) + 1})
            claimed.append(deepcopy(row))
        return claimed

    def renew_task_lease(self, outbox_id: str, owner: str, expires_at: datetime) -> dict[str, Any] | None:
        row = self.outbox.get(outbox_id)
        if row is None or row.get("claimed_by") != owner or row.get("status") != "claimed":
            return None
        row["lease_expires_at"] = expires_at
        return deepcopy(row)

    def complete_task(self, outbox_id: str, owner: str) -> dict[str, Any] | None:
        row = self.outbox.get(outbox_id)
        if row is None or row.get("claimed_by") != owner:
            return None
        row.update({"status": "complete", "delivered_at": _now(), "lease_expires_at": None})
        return deepcopy(row)

    def fail_task(self, outbox_id: str, owner: str, error: dict[str, Any] | Exception,
                  next_attempt_at: datetime | None = None) -> dict[str, Any] | None:
        row = self.outbox.get(outbox_id)
        if row is None or row.get("claimed_by") != owner:
            return None
        code, message = _error_parts(error)
        if int(row.get("attempt") or 0) >= int(row.get("max_attempts") or 3):
            return self.dead_letter_task(outbox_id, owner, error)
        row.update({"status": "retry", "next_attempt_at": next_attempt_at or _retry_at(int(row.get("attempt") or 0), outbox_id),
                    "last_error_code": code, "last_error_message": message, "lease_expires_at": None,
                    "claimed_by": None})
        return deepcopy(row)

    def dead_letter_task(self, outbox_id: str, owner: str, error: dict[str, Any] | Exception) -> dict[str, Any] | None:
        row = self.outbox.get(outbox_id)
        if row is None or row.get("claimed_by") != owner:
            return None
        code, message = _error_parts(error)
        row.update({"status": "dead_lettered", "dead_lettered_at": _now(), "last_error_code": code,
                    "last_error_message": message, "lease_expires_at": None, "claimed_by": None})
        return deepcopy(row)

    def save_checkpoint_once(self, state: dict[str, Any]) -> dict[str, Any]:
        key = (state["run_id"], state["stage"], int(state["attempt"]))
        existing = self.checkpoints.get(key)
        if existing:
            return deepcopy(existing)
        stored = deepcopy({**state, "created_at": _now(), "updated_at": _now()})
        self.checkpoints[key] = stored
        return deepcopy(stored)

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        rows = [row for row in self.checkpoints.values() if row["run_id"] == run_id]
        return deepcopy(max(rows, key=lambda row: (row["created_at"], row["attempt"]))) if rows else None

    def append_event_once(self, run_id: str, event_id: str, stage: str, status: str,
                          payload: dict[str, Any] | None = None, scene_id: str | None = None) -> dict[str, Any]:
        for row in self.events.get(run_id, []):
            if row["event_id"] == event_id:
                return deepcopy(row)
        return self.append_event({"event_id": event_id, "run_id": run_id, "stage": stage,
                                  "status": status, "payload": payload or {}, "scene_id": scene_id})

    def save_scene_revision_once(self, row: dict[str, Any]) -> dict[str, Any]:
        existing = next((item for item in self.scene_revisions.get(row["scene_id"], [])
                         if row.get("idempotency_key") and item.get("idempotency_key") == row["idempotency_key"]
                         or item.get("revision_no") == row.get("revision_no")), None)
        if existing:
            return deepcopy(existing)
        return self.save_scene_revision(row)

    def create_candidate_release_once(self, row: dict[str, Any]) -> dict[str, Any]:
        with self._scene_claim_lock:
            existing = next((item for item in self.releases.values()
                             if item["run_id"] == row["run_id"] and item["candidate_no"] == row["candidate_no"]), None)
            if existing:
                return deepcopy(existing)
            stored = deepcopy({**row, "created_at": _now()})
            self.releases[row["release_id"]] = stored
            return deepcopy(stored)

    def next_candidate_no(self, run_id: str) -> int:
        return max((int(item.get("candidate_no") or 0) for item in self.releases.values()
                    if item.get("run_id") == run_id), default=0) + 1

    def commit_release_once(self, release_id: str, *, resource_id: str | None = None,
                            resource_projection: dict[str, Any] | None = None,
                            job_status: str | None = None, warnings: list[dict[str, Any]] | None = None,
                            manifest: dict[str, Any] | None = None,
                            event_payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self._scene_claim_lock:
            release = self.releases.get(release_id)
            if release is None:
                return None
            if release.get("status") == "released":
                return deepcopy(release)
            release.update({"status": "released", "resource_id": resource_id or release.get("resource_id"), "released_at": _now()})
            if manifest is not None:
                release["manifest_json"] = deepcopy(manifest)
                release["manifest_sha256"] = hashlib.sha256(
                    json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                ).hexdigest()
            resource = self.resources.get(release.get("resource_id"))
            if resource is not None:
                resource.update({"status": "published", "released_release_id": release_id})
                if resource_projection:
                    resource.update(deepcopy(resource_projection))
            job = self.jobs.get(release["run_id"])
            if job is not None:
                job["released_release_id"] = release_id
                if release.get("resource_id"):
                    job["resource_id"] = release["resource_id"]
                if job_status:
                    job["status"] = job_status
                if warnings is not None:
                    job["warnings"] = deepcopy(warnings)
            if event_payload:
                self.append_event_once(release["run_id"], event_payload["event_id"], "publishing", "released", event_payload)
            return deepcopy(release)

    def block_release_once(self, release_id: str, *, error_code: str, error_message: str) -> dict[str, Any] | None:
        release = self.releases.get(release_id)
        if release is None:
            return None
        if release.get("status") != "released":
            release.update({"status": "blocked", "error_code": error_code, "error_message": error_message})
            job = self.jobs.get(release.get("run_id"))
            if job is not None:
                job.update({"status": "release_blocked", "error_code": error_code, "error_message": error_message})
        return deepcopy(release)

    def list_outbox(self, run_id: str | None = None, *, pending_only: bool = True) -> list[dict[str, Any]]:
        rows = self.outbox.values()
        return [deepcopy(item) for item in rows if (run_id is None or item["run_id"] == run_id)
                and (not pending_only or item.get("delivered_at") is None)]

    def mark_outbox_delivered(self, outbox_id: str) -> dict[str, Any] | None:
        row = self.outbox.get(outbox_id)
        if row is None:
            return None
        row["delivered_at"] = _now()
        return deepcopy(row)

    def save_review(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy({**row, "created_at": _now()})
        self.reviews[row["review_id"]] = stored
        return deepcopy(stored)

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self.reviews.values() if row["run_id"] == run_id]

    def append_event(self, row: dict[str, Any]) -> dict[str, Any]:
        events = self.events.setdefault(row["run_id"], [])
        job = self.jobs.get(row["run_id"])
        if job is not None:
            sequence = int(job.get("next_event_sequence") or 1)
            job["next_event_sequence"] = sequence + 1
        else:
            sequence = len(events) + 1
        stored = deepcopy({**row, "event_sequence": sequence, "created_at": _now()})
        events.append(stored)
        return deepcopy(stored)

    def list_events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self.events.get(run_id, []) if row["event_sequence"] > after_sequence]

    def ingest_learning_events(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted = []
        for raw in rows:
            event_id = str(raw.get("event_id") or raw.get("occurrence_id"))
            if event_id in self.learning_events:
                accepted.append(deepcopy(self.learning_events[event_id])); continue
            self._learning_sequence += 1
            state = {key: raw.get("state", {}).get(key) for key in {"scene_index", "scene_count", "correct", "completed", "attempt", "duration_ms"} if key in (raw.get("state") or {})}
            stored = deepcopy({**raw, "event_id": event_id, "occurrence_id": raw.get("occurrence_id") or event_id, "state": state, "sequence": self._learning_sequence, "created_at": _now()})
            self.learning_events[event_id] = stored; accepted.append(deepcopy(stored))
        return accepted

    def list_learning_events(self, *, resource_id: str, release_id: str) -> list[dict[str, Any]]:
        return sorted((deepcopy(row) for row in self.learning_events.values() if row.get("resource_id") == resource_id and row.get("release_id") == release_id), key=lambda row: (row.get("sequence", 0), row.get("event_id", "")))

    def learning_progress(self, *, resource_id: str, release_id: str) -> dict[str, Any]:
        rows = self.list_learning_events(resource_id=resource_id, release_id=release_id)
        return {"resource_id": resource_id, "release_id": release_id,
                "viewed_scene_ids": sorted({r.get("scene_id") for r in rows if r.get("event_type") == "scene_viewed" and r.get("scene_id")}),
                "completed_scene_ids": sorted({r.get("scene_id") for r in rows if r.get("event_type") == "scene_completed" and r.get("scene_id")}),
                "courseware_completed": any(r.get("event_type") == "courseware_completed" for r in rows),
                "answer_count": sum(r.get("event_type") == "answer_submitted" for r in rows)}

    def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy({**row, "created_at": _now()})
        self.artifacts[row["artifact_id"]] = stored
        return deepcopy(stored)

    def list_artifacts(self, resource_id: str) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self.artifacts.values() if row["courseware_resource_id"] == resource_id]


class SQLCoursewareRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def create_job(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            existing = db.query(CoursewareGenerationJobORM).filter_by(
                learner_id=row["learner_id"], request_hash=row["request_hash"],
            ).one_or_none()
            if existing:
                return _job_row(existing)
            db.add(CoursewareGenerationJobORM(**row))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.query(CoursewareGenerationJobORM).filter_by(
                    learner_id=row["learner_id"], request_hash=row["request_hash"],
                ).one()
                return _job_row(existing)
            return _job_row(db.get(CoursewareGenerationJobORM, row["run_id"]))

    def create_job_with_task_once(self, row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            existing = db.query(CoursewareGenerationJobORM).filter_by(
                learner_id=row["learner_id"], request_hash=row["request_hash"],
            ).one_or_none()
            if existing is None:
                existing = CoursewareGenerationJobORM(**row)
                db.add(existing)
                db.flush()
            task_row = db.query(CoursewareOutboxORM).filter_by(
                idempotency_key=f"courseware.run:{existing.run_id}"
            ).one_or_none()
            if task_row is None:
                task_row = CoursewareOutboxORM(**{**task,
                    "run_id": existing.run_id,
                    "outbox_id": f"cwo_{existing.run_id}",
                    "idempotency_key": f"courseware.run:{existing.run_id}"})
                db.add(task_row)
            event_id = f"{existing.run_id}:queued"
            event = db.get(CoursewareEventORM, event_id)
            if event is None:
                sequence = int(existing.next_event_sequence or 1)
                existing.next_event_sequence = sequence + 1
                db.add(CoursewareEventORM(
                    event_id=event_id, run_id=existing.run_id, event_sequence=sequence,
                    stage="job", status="queued", payload={},
                ))
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.query(CoursewareGenerationJobORM).filter_by(
                    learner_id=row["learner_id"], request_hash=row["request_hash"],
                ).one()
            else:
                db.refresh(existing)
            return _job_row(existing)

    def get_job(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareGenerationJobORM, run_id)
            return _job_row(row) if row else None

    def update_job(self, run_id: str, **changes: Any) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareGenerationJobORM, run_id)
            if row is None:
                return None
            for name, value in changes.items():
                setattr(row, name, value)
            db.commit()
            db.refresh(row)
            return _job_row(row)

    def save_resource(self, row: dict[str, Any], links: list[dict[str, Any]]) -> dict[str, Any]:
        with self.session_factory() as db:
            existing = db.get(CoursewareResourceORM, row["resource_id"])
            if existing:
                return _resource_row(existing)
            db.add(CoursewareResourceORM(**row))
            for link in links:
                db.add(CoursewareSourceLinkORM(**link))
            db.commit()
            return _resource_row(db.get(CoursewareResourceORM, row["resource_id"]))

    def update_resource_status(self, resource_id: str, status: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareResourceORM, resource_id)
            if row is None:
                return None
            row.status = status
            db.commit()
            db.refresh(row)
            return _resource_row(row)

    def update_resource_artifact(self, resource_id: str, **changes: Any) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareResourceORM, resource_id)
            if row is None:
                return None
            for name, value in changes.items():
                setattr(row, name, value)
            db.commit()
            db.refresh(row)
            return _resource_row(row)

    def get_resource(self, resource_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareResourceORM, resource_id)
            return _resource_row(row) if row else None

    def get_resource_by_run(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareResourceORM).filter_by(run_id=run_id).one_or_none()
            return _resource_row(row) if row else None

    def list_resources(self, learner_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareResourceORM).filter_by(learner_id=learner_id).order_by(
                CoursewareResourceORM.published_at.desc()
            ).all()
            return [_resource_row(row) for row in rows]

    def get_links(self, resource_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareSourceLinkORM).filter_by(courseware_resource_id=resource_id).all()
            return [
                {"source_resource_id": row.source_resource_id, "source_run_id": row.source_run_id,
                 "source_version": row.source_version, "source_content_hash": row.source_content_hash,
                 "source_role": row.source_role, "source_snapshot": row.source_snapshot}
                for row in rows
            ]

    def save_spec(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            stored = db.get(CoursewareSpecORM, row["spec_id"])
            if stored is None:
                stored = CoursewareSpecORM(**row)
                db.add(stored)
            else:
                for name, value in row.items():
                    setattr(stored, name, value)
            db.commit()
            db.refresh(stored)
            return {name: getattr(stored, name) for name in row} | {"created_at": stored.created_at}

    def get_spec_by_run(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareSpecORM).filter_by(run_id=run_id).order_by(CoursewareSpecORM.created_at.desc()).first()
            if row is None:
                return None
            return {
                "spec_id": row.spec_id, "run_id": row.run_id, "schema_version": row.schema_version,
                "prompt_version": row.prompt_version, "runtime_version": row.runtime_version,
                "spec_json": row.spec_json, "content_hash": row.content_hash, "status": row.status,
                "created_at": row.created_at,
            }

    def upsert_scene(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            stored = db.get(CoursewareSceneORM, row["scene_id"])
            if stored is None:
                stored = CoursewareSceneORM(**row)
                db.add(stored)
            else:
                for name, value in row.items():
                    setattr(stored, name, value)
            db.commit()
            db.refresh(stored)
            return {
                "scene_id": stored.scene_id, "spec_id": stored.spec_id, "scene_order": stored.scene_order,
                "kind": stored.kind, "scene_json": stored.scene_json, "content_hash": stored.content_hash,
                "status": stored.status, "attempt": stored.attempt, "error_code": stored.error_code,
                "error_message": stored.error_message, "created_at": stored.created_at, "updated_at": stored.updated_at,
            }

    def get_scene(self, scene_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareSceneORM, scene_id)
            if row is None:
                return None
            return self._scene_row(row)

    def claim_scene(self, scene_id: str, owner: str, lease_seconds: int = 120) -> dict[str, Any] | None:
        with self.session_factory() as db:
            now = _now()
            result = db.execute(
                update(CoursewareSceneORM)
                .where(
                    CoursewareSceneORM.scene_id == scene_id,
                    or_(
                        CoursewareSceneORM.lease_expires_at.is_(None),
                        CoursewareSceneORM.lease_expires_at <= now,
                    ),
                )
                .values(
                    lease_owner=owner,
                    lease_expires_at=now + timedelta(seconds=lease_seconds),
                )
            )
            if result.rowcount != 1:
                return None
            db.commit()
            row = db.get(CoursewareSceneORM, scene_id)
            if row is None:
                return None
            db.refresh(row)
            return self._scene_row(row)

    @staticmethod
    def _scene_row(row: CoursewareSceneORM) -> dict[str, Any]:
        return {
            "scene_id": row.scene_id, "spec_id": row.spec_id, "scene_order": row.scene_order,
            "kind": row.kind, "scene_json": row.scene_json, "content_hash": row.content_hash,
            "status": row.status, "attempt": row.attempt, "input_snapshot_hash": row.input_snapshot_hash,
            "agent_version": row.agent_version, "prompt_version": row.prompt_version,
            "review_instruction": row.review_instruction, "approved_at": row.approved_at,
            "lease_owner": row.lease_owner, "lease_expires_at": row.lease_expires_at, "error_code": row.error_code,
            "error_message": row.error_message, "created_at": row.created_at, "updated_at": row.updated_at,
        }

    def list_scenes(self, spec_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareSceneORM).filter_by(spec_id=spec_id).order_by(CoursewareSceneORM.scene_order).all()
            return [self._scene_row(row) for row in rows]

    def save_scene_revision(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            stored = CoursewareSceneRevisionORM(**row)
            db.add(stored)
            db.commit()
            db.refresh(stored)
            return {"revision_id": stored.revision_id, "scene_id": stored.scene_id,
                    "revision_no": stored.revision_no, "trigger": stored.trigger,
                    "actor_id": stored.actor_id, "reason": stored.reason,
                    "before_content_hash": stored.before_content_hash,
                    "after_content_hash": stored.after_content_hash,
                    "input_snapshot_hash": stored.input_snapshot_hash, "idempotency_key": stored.idempotency_key,
                    "created_at": stored.created_at}

    def save_scene_revision_once(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            query = db.query(CoursewareSceneRevisionORM)
            if row.get("idempotency_key"):
                existing = query.filter_by(idempotency_key=row["idempotency_key"]).one_or_none()
            else:
                existing = query.filter_by(scene_id=row["scene_id"], revision_no=row["revision_no"]).one_or_none()
            if existing is None:
                existing = CoursewareSceneRevisionORM(**row)
                db.add(existing)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    if row.get("idempotency_key"):
                        existing = query.filter_by(idempotency_key=row["idempotency_key"]).one()
                    else:
                        existing = query.filter_by(scene_id=row["scene_id"], revision_no=row["revision_no"]).one()
                else:
                    db.refresh(existing)
            return {"revision_id": existing.revision_id, "scene_id": existing.scene_id,
                    "revision_no": existing.revision_no, "trigger": existing.trigger,
                    "actor_id": existing.actor_id, "reason": existing.reason,
                    "before_content_hash": existing.before_content_hash,
                    "after_content_hash": existing.after_content_hash,
                    "input_snapshot_hash": existing.input_snapshot_hash,
                    "idempotency_key": existing.idempotency_key, "created_at": existing.created_at}

    def list_scene_revisions(self, scene_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareSceneRevisionORM).filter_by(scene_id=scene_id).order_by(
                CoursewareSceneRevisionORM.revision_no
            ).all()
            return [{"revision_id": row.revision_id, "scene_id": row.scene_id,
                     "revision_no": row.revision_no, "trigger": row.trigger,
                     "actor_id": row.actor_id, "reason": row.reason,
                     "before_content_hash": row.before_content_hash,
                     "after_content_hash": row.after_content_hash,
                     "input_snapshot_hash": row.input_snapshot_hash, "idempotency_key": row.idempotency_key,
                     "created_at": row.created_at} for row in rows]

    def enqueue_outbox(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            existing = db.query(CoursewareOutboxORM).filter_by(idempotency_key=row["idempotency_key"]).one_or_none()
            if existing is None:
                existing = CoursewareOutboxORM(**row)
                db.add(existing)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    existing = db.query(CoursewareOutboxORM).filter_by(
                        idempotency_key=row["idempotency_key"]
                    ).one()
                else:
                    db.refresh(existing)
            return _outbox_row(existing)

    def enqueue_task_once(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.enqueue_outbox({"task_kind": "courseware.run", "status": "queued", "attempt": 0,
                                    "max_attempts": 3, **row})

    def claim_task_batch(self, owner: str, now: datetime | None = None, limit: int = 10,
                         lease_seconds: int = 120) -> list[dict[str, Any]]:
        now = now or _now()
        with self.session_factory() as db:
            is_sqlite = db.bind.dialect.name == "sqlite"
            if is_sqlite:
                # SQLite has no SKIP LOCKED. BEGIN IMMEDIATE serializes the
                # short claim transaction, while each row is still guarded by
                # a conditional CAS update below.
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            query = db.query(CoursewareOutboxORM).filter(
                CoursewareOutboxORM.delivered_at.is_(None),
                or_(CoursewareOutboxORM.status.in_(["queued", "retry"]),
                    (CoursewareOutboxORM.status == "claimed") & (CoursewareOutboxORM.lease_expires_at <= now)),
                or_(CoursewareOutboxORM.next_attempt_at.is_(None), CoursewareOutboxORM.next_attempt_at <= now),
                or_(CoursewareOutboxORM.lease_expires_at.is_(None), CoursewareOutboxORM.lease_expires_at <= now),
                or_(CoursewareOutboxORM.claimed_by.is_(None), CoursewareOutboxORM.lease_expires_at <= now),
            ).order_by(CoursewareOutboxORM.created_at).limit(limit)
            if not is_sqlite and db.bind.dialect.name == "postgresql":
                query = query.with_for_update(skip_locked=True)
            rows = query.all()
            claimed_ids: list[str] = []
            lease_until = now + timedelta(seconds=lease_seconds)
            for row in rows:
                result = db.execute(
                    update(CoursewareOutboxORM).execution_options(synchronize_session=False)
                    .where(
                        CoursewareOutboxORM.outbox_id == row.outbox_id,
                        CoursewareOutboxORM.delivered_at.is_(None),
                        or_(CoursewareOutboxORM.status.in_(["queued", "retry"]),
                            (CoursewareOutboxORM.status == "claimed") & (CoursewareOutboxORM.lease_expires_at <= now)),
                        or_(CoursewareOutboxORM.next_attempt_at.is_(None), CoursewareOutboxORM.next_attempt_at <= now),
                        or_(CoursewareOutboxORM.lease_expires_at.is_(None), CoursewareOutboxORM.lease_expires_at <= now),
                        or_(CoursewareOutboxORM.claimed_by.is_(None), CoursewareOutboxORM.lease_expires_at <= now),
                    )
                    .values(status="claimed", claimed_by=owner, lease_expires_at=lease_until,
                            attempt=CoursewareOutboxORM.attempt + 1)
                )
                if result.rowcount == 1:
                    claimed_ids.append(row.outbox_id)
            db.commit()
            if not claimed_ids:
                return []
            claimed = db.query(CoursewareOutboxORM).filter(
                CoursewareOutboxORM.outbox_id.in_(claimed_ids),
                CoursewareOutboxORM.claimed_by == owner,
                CoursewareOutboxORM.status == "claimed",
            ).all()
            by_id = {row.outbox_id: row for row in claimed}
            return [_outbox_row(by_id[outbox_id]) for outbox_id in claimed_ids if outbox_id in by_id]

    def renew_task_lease(self, outbox_id: str, owner: str, expires_at: datetime) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareOutboxORM).filter_by(outbox_id=outbox_id, claimed_by=owner, status="claimed").one_or_none()
            if row is None:
                return None
            row.lease_expires_at = expires_at; db.commit(); db.refresh(row)
            return _outbox_row(row)

    def complete_task(self, outbox_id: str, owner: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareOutboxORM).filter_by(outbox_id=outbox_id, claimed_by=owner, status="claimed").one_or_none()
            if row is None:
                return None
            row.status = "complete"; row.delivered_at = _now(); row.lease_expires_at = None
            db.commit(); db.refresh(row); return _outbox_row(row)

    def fail_task(self, outbox_id: str, owner: str, error: dict[str, Any] | Exception,
                  next_attempt_at: datetime | None = None) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareOutboxORM).filter_by(outbox_id=outbox_id, claimed_by=owner, status="claimed").one_or_none()
            if row is None:
                return None
            if int(row.attempt or 0) >= int(row.max_attempts or 3):
                row.status = "dead_lettered"; row.dead_lettered_at = _now()
            else:
                row.status = "retry"; row.next_attempt_at = next_attempt_at or _retry_at(int(row.attempt or 0), outbox_id)
            row.last_error_code, row.last_error_message = _error_parts(error)
            row.lease_expires_at = None; row.claimed_by = None
            db.commit(); db.refresh(row); return _outbox_row(row)

    def dead_letter_task(self, outbox_id: str, owner: str, error: dict[str, Any] | Exception) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareOutboxORM).filter_by(outbox_id=outbox_id, claimed_by=owner, status="claimed").one_or_none()
            if row is None:
                return None
            row.status = "dead_lettered"; row.dead_lettered_at = _now(); row.lease_expires_at = None; row.claimed_by = None
            row.last_error_code, row.last_error_message = _error_parts(error)
            db.commit(); db.refresh(row); return _outbox_row(row)

    def save_checkpoint_once(self, state: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            row = db.query(CoursewareWorkflowCheckpointORM).filter_by(
                run_id=state["run_id"], stage=state["stage"], attempt=state["attempt"]
            ).one_or_none()
            if row is None:
                row = CoursewareWorkflowCheckpointORM(**state); db.add(row)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    row = db.query(CoursewareWorkflowCheckpointORM).filter_by(
                        run_id=state["run_id"], stage=state["stage"], attempt=state["attempt"]
                    ).one()
                else:
                    db.refresh(row)
            return {name: getattr(row, name) for name in state} | {"created_at": row.created_at, "updated_at": row.updated_at}

    def latest_checkpoint(self, run_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.query(CoursewareWorkflowCheckpointORM).filter_by(run_id=run_id).order_by(
                CoursewareWorkflowCheckpointORM.created_at.desc(), CoursewareWorkflowCheckpointORM.attempt.desc()
            ).first()
            if row is None:
                return None
            fields = ("checkpoint_id", "run_id", "stage", "attempt", "state_json", "input_hash", "output_hash", "workflow_version")
            return {name: getattr(row, name) for name in fields} | {"created_at": row.created_at, "updated_at": row.updated_at}

    @staticmethod
    def _checkpoint_row(row: CoursewareWorkflowCheckpointORM) -> dict[str, Any]:
        fields = ("checkpoint_id", "run_id", "stage", "attempt", "state_json", "input_hash", "output_hash", "workflow_version")
        return {name: getattr(row, name) for name in fields} | {"created_at": row.created_at, "updated_at": row.updated_at}

    @staticmethod
    def _release_row(row: CoursewareReleaseORM) -> dict[str, Any]:
        fields = ("release_id", "run_id", "resource_id", "candidate_no", "status", "release_policy",
                  "scene_set_hash", "snapshot_set_hash", "manifest_json", "manifest_sha256",
                  "provenance_json", "error_code", "error_message", "created_at", "released_at", "updated_at")
        return {name: getattr(row, name) for name in fields}

    def create_candidate_release_once(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            query = db.query(CoursewareReleaseORM).filter_by(
                run_id=row["run_id"], candidate_no=row["candidate_no"]
            )
            existing = query.one_or_none()
            if existing is None:
                existing = CoursewareReleaseORM(**row)
                db.add(existing)
                try:
                    db.commit()
                except IntegrityError:
                    db.rollback()
                    existing = query.one()
                else:
                    db.refresh(existing)
            return self._release_row(existing)

    def next_candidate_no(self, run_id: str) -> int:
        with self.session_factory() as db:
            value = db.query(CoursewareReleaseORM.candidate_no).filter_by(run_id=run_id).order_by(
                CoursewareReleaseORM.candidate_no.desc()).first()
            return int(value[0]) + 1 if value else 1

    def commit_release_once(self, release_id: str, *, resource_id: str | None = None,
                            resource_projection: dict[str, Any] | None = None,
                            job_status: str | None = None, warnings: list[dict[str, Any]] | None = None,
                            manifest: dict[str, Any] | None = None,
                            event_payload: dict[str, Any] | None = None) -> dict[str, Any] | None:
        with self.session_factory() as db:
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            query = db.query(CoursewareReleaseORM).filter_by(release_id=release_id)
            if db.bind.dialect.name == "postgresql":
                query = query.with_for_update()
            release = query.one_or_none()
            if release is None:
                return None
            if release.status != "released":
                release.status = "released"
                release.resource_id = resource_id or release.resource_id
                release.released_at = _now()
                if manifest is not None:
                    release.manifest_json = manifest
                    release.manifest_sha256 = hashlib.sha256(
                        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
                    ).hexdigest()
                if release.resource_id:
                    resource = db.get(CoursewareResourceORM, release.resource_id)
                    if resource is not None:
                        resource.released_release_id = release.release_id
                        resource.status = "published"
                        if resource_projection:
                            for name, value in resource_projection.items():
                                setattr(resource, name, value)
                job = db.get(CoursewareGenerationJobORM, release.run_id)
                if job is not None:
                    job.released_release_id = release.release_id
                    if release.resource_id:
                        job.resource_id = release.resource_id
                    if job_status:
                        job.status = job_status
                    if warnings is not None:
                        job.warnings = warnings
            if event_payload:
                event_id = event_payload.get("event_id")
                if event_id and db.query(CoursewareEventORM).filter_by(event_id=event_id).one_or_none() is None:
                    self._append_event_in_session(db, {**event_payload, "run_id": release.run_id,
                                                        "stage": event_payload.get("stage", "publishing"),
                                                        "status": event_payload.get("status", "released")})
            db.commit()
            db.refresh(release)
            return self._release_row(release)

    def block_release_once(self, release_id: str, *, error_code: str, error_message: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            release = db.get(CoursewareReleaseORM, release_id)
            if release is None:
                return None
            if release.status != "released":
                release.status = "blocked"
                release.error_code = error_code
                release.error_message = error_message
                job = db.get(CoursewareGenerationJobORM, release.run_id)
                if job is not None:
                    job.status = "release_blocked"
                    job.error_code = error_code
                    job.error_message = error_message
            db.commit()
            db.refresh(release)
            return self._release_row(release)

    def list_outbox(self, run_id: str | None = None, *, pending_only: bool = True) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            query = db.query(CoursewareOutboxORM)
            if run_id is not None:
                query = query.filter_by(run_id=run_id)
            if pending_only:
                query = query.filter(CoursewareOutboxORM.delivered_at.is_(None))
            rows = query.order_by(CoursewareOutboxORM.created_at).all()
            return [_outbox_row(row) for row in rows]

    def mark_outbox_delivered(self, outbox_id: str) -> dict[str, Any] | None:
        with self.session_factory() as db:
            row = db.get(CoursewareOutboxORM, outbox_id)
            if row is None:
                return None
            row.delivered_at = _now()
            db.commit()
            db.refresh(row)
            return _outbox_row(row)

    def save_review(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            stored = db.get(CoursewareReviewORM, row["review_id"])
            if stored is None:
                stored = CoursewareReviewORM(**row)
                db.add(stored)
                db.commit()
                db.refresh(stored)
            return {name: getattr(stored, name) for name in row} | {"created_at": stored.created_at}

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareReviewORM).filter_by(run_id=run_id).order_by(CoursewareReviewORM.created_at).all()
            return [{
                "review_id": row.review_id, "run_id": row.run_id, "scene_id": row.scene_id,
                "kind": row.kind, "decision": row.decision, "issues": row.issues or [],
                "reviewer_version": row.reviewer_version, "created_at": row.created_at,
            } for row in rows]

    def ingest_learning_events(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        safe_keys = {"scene_index", "scene_count", "correct", "completed", "attempt", "duration_ms"}
        with self.session_factory() as db:
            result = []
            for raw in rows:
                event_id = str(raw.get("event_id") or raw.get("occurrence_id"))
                existing = db.get(CoursewareLearningEventORM, event_id)
                if existing is not None:
                    result.append(self._learning_event_row(existing)); continue
                occurrence = str(raw.get("occurrence_id") or event_id)
                duplicate = db.query(CoursewareLearningEventORM).filter_by(occurrence_id=occurrence).one_or_none()
                if duplicate is not None:
                    result.append(self._learning_event_row(duplicate)); continue
                sequence = int(db.query(CoursewareLearningEventORM.sequence).order_by(CoursewareLearningEventORM.sequence.desc()).first()[0] or 0) + 1 if db.query(CoursewareLearningEventORM.sequence).first() else 1
                state = {k: (raw.get("state") or {}).get(k) for k in safe_keys if k in (raw.get("state") or {})}
                values = {**raw, "event_id": event_id, "occurrence_id": occurrence, "state": state, "sequence": sequence}
                values.pop("created_at", None)
                row = CoursewareLearningEventORM(**values); db.add(row); db.flush(); result.append(self._learning_event_row(row))
            db.commit(); return result

    @staticmethod
    def _learning_event_row(row: CoursewareLearningEventORM) -> dict[str, Any]:
        return {name: getattr(row, name) for name in ("event_id", "occurrence_id", "event_schema_version", "event_type", "resource_id", "resource_version", "release_id", "release_version", "scene_id", "scene_version", "component_id", "component_version", "state", "sequence", "occurred_at", "created_at")}

    def list_learning_events(self, *, resource_id: str, release_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareLearningEventORM).filter_by(resource_id=resource_id, release_id=release_id).order_by(CoursewareLearningEventORM.sequence, CoursewareLearningEventORM.event_id).all()
            return [self._learning_event_row(row) for row in rows]

    def learning_progress(self, *, resource_id: str, release_id: str) -> dict[str, Any]:
        rows = self.list_learning_events(resource_id=resource_id, release_id=release_id)
        return {"resource_id": resource_id, "release_id": release_id,
                "viewed_scene_ids": sorted({r.get("scene_id") for r in rows if r.get("event_type") == "scene_viewed" and r.get("scene_id")}),
                "completed_scene_ids": sorted({r.get("scene_id") for r in rows if r.get("event_type") == "scene_completed" and r.get("scene_id")}),
                "courseware_completed": any(r.get("event_type") == "courseware_completed" for r in rows),
                "answer_count": sum(r.get("event_type") == "answer_submitted" for r in rows)}

    @staticmethod
    def _event_row(stored: CoursewareEventORM) -> dict[str, Any]:
        return {
            "event_id": stored.event_id, "run_id": stored.run_id,
            "event_sequence": stored.event_sequence, "stage": stored.stage,
            "scene_id": stored.scene_id, "status": stored.status,
            "payload": stored.payload or {}, "created_at": stored.created_at,
        }

    @staticmethod
    def _append_event_in_session(db: Session, row: dict[str, Any]) -> CoursewareEventORM:
        job_query = db.query(CoursewareGenerationJobORM).filter_by(run_id=row["run_id"])
        if db.bind.dialect.name == "postgresql":
            job_query = job_query.with_for_update()
        job = job_query.one_or_none()
        if job is None:
            raise ValueError(f"courseware run not found: {row['run_id']}")
        sequence = int(job.next_event_sequence or 1)
        job.next_event_sequence = sequence + 1
        stored = CoursewareEventORM(**row, event_sequence=sequence)
        db.add(stored)
        return stored

    def append_event_once(self, run_id: str, event_id: str, stage: str, status: str,
                          payload: dict[str, Any] | None = None, scene_id: str | None = None) -> dict[str, Any]:
        with self.session_factory() as db:
            if db.bind.dialect.name == "sqlite":
                db.connection().exec_driver_sql("BEGIN IMMEDIATE")
            existing = db.get(CoursewareEventORM, event_id)
            if existing is not None:
                return self._event_row(existing)
            stored = self._append_event_in_session(db, {"event_id": event_id, "run_id": run_id,
                                                        "stage": stage, "status": status,
                                                        "payload": payload or {}, "scene_id": scene_id})
            try:
                db.commit()
            except IntegrityError:
                db.rollback()
                existing = db.get(CoursewareEventORM, event_id)
                if existing is None:
                    raise
                return self._event_row(existing)
            db.refresh(stored)
            return self._event_row(stored)

    def append_event(self, row: dict[str, Any]) -> dict[str, Any]:
        return self.append_event_once(row["run_id"], row["event_id"], row["stage"], row["status"],
                                      row.get("payload"), row.get("scene_id"))

    def list_events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareEventORM).filter(
                CoursewareEventORM.run_id == run_id,
                CoursewareEventORM.event_sequence > after_sequence,
            ).order_by(CoursewareEventORM.event_sequence).all()
            return [{
                "event_id": row.event_id, "run_id": row.run_id, "event_sequence": row.event_sequence,
                "stage": row.stage, "scene_id": row.scene_id, "status": row.status,
                "payload": row.payload or {}, "created_at": row.created_at,
            } for row in rows]

    def save_artifact(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            stored = db.get(CoursewareArtifactORM, row["artifact_id"])
            if stored is None:
                stored = CoursewareArtifactORM(**row)
                db.add(stored)
                db.commit()
                db.refresh(stored)
            return {name: getattr(stored, name) for name in row} | {"created_at": stored.created_at}

    def list_artifacts(self, resource_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareArtifactORM).filter_by(courseware_resource_id=resource_id).order_by(
                CoursewareArtifactORM.created_at).all()
            return [{
                "artifact_id": row.artifact_id, "courseware_resource_id": row.courseware_resource_id,
                "release_id": row.release_id, "required": bool(row.required),
                "artifact_status": row.artifact_status,
                "artifact_format": row.artifact_format, "file_path": row.file_path,
                "mime_type": row.mime_type, "file_size": row.file_size, "sha256": row.sha256,
                "manifest": row.manifest or {}, "created_at": row.created_at,
            } for row in rows]


def create_courseware_repository(db_type: str, session_factory: Callable[[], Session] | None = None):
    if db_type == "memory":
        return MemoryCoursewareRepository()
    if db_type not in {"sqlite", "postgresql"} or session_factory is None:
        raise ValueError("courseware repository requires a supported database session")
    return SQLCoursewareRepository(session_factory)
