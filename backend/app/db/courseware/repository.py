"""Small repository with memory and SQL implementations for courseware."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Callable

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.courseware.models import (
    CoursewareArtifactORM,
    CoursewareEventORM,
    CoursewareGenerationJobORM,
    CoursewareReviewORM,
    CoursewareResourceORM,
    CoursewareSceneORM,
    CoursewareSourceLinkORM,
    CoursewareSpecORM,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job_row(row: CoursewareGenerationJobORM) -> dict[str, Any]:
    return {
        "run_id": row.run_id, "learner_id": row.learner_id,
        "knowledge_base_id": row.knowledge_base_id, "title": row.title,
        "publish_mode": row.publish_mode,
        "source_resource_ids": row.source_resource_ids or [],
        "source_snapshots": row.source_snapshots or [], "request_hash": row.request_hash,
        "idempotency_key": row.idempotency_key, "status": row.status,
        "warnings": row.warnings or [], "error_code": row.error_code,
        "error_message": row.error_message, "resource_id": row.resource_id,
        "attempt": row.attempt or 0, "created_at": row.created_at, "updated_at": row.updated_at,
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
    }


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

    def list_scenes(self, spec_id: str) -> list[dict[str, Any]]:
        rows = (deepcopy(row) for row in self.scenes.values() if row["spec_id"] == spec_id)
        return sorted(rows, key=lambda row: row["scene_order"])

    def save_review(self, row: dict[str, Any]) -> dict[str, Any]:
        stored = deepcopy({**row, "created_at": _now()})
        self.reviews[row["review_id"]] = stored
        return deepcopy(stored)

    def list_reviews(self, run_id: str) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self.reviews.values() if row["run_id"] == run_id]

    def append_event(self, row: dict[str, Any]) -> dict[str, Any]:
        events = self.events.setdefault(row["run_id"], [])
        stored = deepcopy({**row, "event_sequence": len(events) + 1, "created_at": _now()})
        events.append(stored)
        return deepcopy(stored)

    def list_events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return [deepcopy(row) for row in self.events.get(run_id, []) if row["event_sequence"] > after_sequence]

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

    @staticmethod
    def _scene_row(row: CoursewareSceneORM) -> dict[str, Any]:
        return {
            "scene_id": row.scene_id, "spec_id": row.spec_id, "scene_order": row.scene_order,
            "kind": row.kind, "scene_json": row.scene_json, "content_hash": row.content_hash,
            "status": row.status, "attempt": row.attempt, "error_code": row.error_code,
            "error_message": row.error_message, "created_at": row.created_at, "updated_at": row.updated_at,
        }

    def list_scenes(self, spec_id: str) -> list[dict[str, Any]]:
        with self.session_factory() as db:
            rows = db.query(CoursewareSceneORM).filter_by(spec_id=spec_id).order_by(CoursewareSceneORM.scene_order).all()
            return [self._scene_row(row) for row in rows]

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

    def append_event(self, row: dict[str, Any]) -> dict[str, Any]:
        with self.session_factory() as db:
            last = db.query(CoursewareEventORM.event_sequence).filter_by(run_id=row["run_id"]).order_by(
                CoursewareEventORM.event_sequence.desc()).first()
            stored = CoursewareEventORM(**row, event_sequence=(last[0] + 1 if last else 1))
            db.add(stored)
            db.commit()
            db.refresh(stored)
            return {
                "event_id": stored.event_id, "run_id": stored.run_id,
                "event_sequence": stored.event_sequence, "stage": stored.stage,
                "scene_id": stored.scene_id, "status": stored.status,
                "payload": stored.payload or {}, "created_at": stored.created_at,
            }

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
