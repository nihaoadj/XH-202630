"""异步生成任务仓储的内存实现。"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.db.generation_job.base import BaseGenerationJobRepository
from app.models.schemas import GenerationJobStatusResponse


class MemoryGenerationJobRepository(BaseGenerationJobRepository):
    def __init__(self):
        self._store: dict[str, dict[str, Any]] = {}

    def create(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
        batch_id: str | None = None,
    ) -> None:
        self._store[run_id] = {
            "run_id": run_id,
            "batch_id": batch_id or run_id,
            "learner_id": learner_id,
            "topic": topic,
            "knowledge_base_id": knowledge_base_id,
            "job_status": "queued",
            "resource_ids": [],
            "error_message": None,
            "superseded_by_run_id": None,
            "created_at": datetime.utcnow(),
            "started_at": None,
            "finished_at": None,
            "request_payload": request_payload,
        }

    def get(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        return GenerationJobStatusResponse(**record) if record else None

    def mark_running(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        if record is None:
            return None
        record["job_status"] = "running"
        record["started_at"] = datetime.utcnow()
        return GenerationJobStatusResponse(**record)

    def mark_completed(self, run_id: str, resource_ids: list[str]) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        if record is None:
            return None
        record["job_status"] = "completed"
        record["resource_ids"] = resource_ids
        record["finished_at"] = datetime.utcnow()
        record["error_message"] = None
        return GenerationJobStatusResponse(**record)

    def mark_failed(self, run_id: str, error_message: str) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        if record is None:
            return None
        record["job_status"] = "failed"
        record["error_message"] = error_message
        record["finished_at"] = datetime.utcnow()
        return GenerationJobStatusResponse(**record)

    def mark_queued(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        if record is None:
            return None
        record["job_status"] = "queued"
        record["error_message"] = None
        record["started_at"] = None
        record["finished_at"] = None
        return GenerationJobStatusResponse(**record)

    def mark_superseded(
        self,
        run_id: str,
        replacement_run_id: str,
    ) -> Optional[GenerationJobStatusResponse]:
        record = self._store.get(run_id)
        if record is None:
            return None
        record["superseded_by_run_id"] = replacement_run_id
        return GenerationJobStatusResponse(**record)

    def fail_incomplete_before(self, before: datetime, error_message: str) -> list[str]:
        cutoff = before.astimezone(timezone.utc).replace(tzinfo=None)
        affected = []
        for run_id, record in self._store.items():
            created_at = record.get("created_at")
            if (
                record["job_status"] in {"queued", "running"}
                and created_at is not None
                and created_at < cutoff
            ):
                record["job_status"] = "failed"
                record["error_message"] = error_message
                record["finished_at"] = datetime.utcnow()
                affected.append(run_id)
        return affected

    def list_by_learner(self, learner_id: str) -> list[GenerationJobStatusResponse]:
        records = [
            GenerationJobStatusResponse(**record)
            for record in self._store.values()
            if record["learner_id"] == learner_id
        ]
        return sorted(records, key=lambda item: item.created_at or datetime.min, reverse=True)
