"""异步生成任务仓储接口定义。"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Optional

from app.models.learning_documents.schemas import GenerationJobStatusResponse


class BaseGenerationJobRepository(ABC):
    @abstractmethod
    def create(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
        batch_id: str | None = None,
    ) -> None:
        pass

    @abstractmethod
    def get(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        pass

    @abstractmethod
    def mark_running(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        pass

    @abstractmethod
    def mark_completed(self, run_id: str, resource_ids: list[str]) -> Optional[GenerationJobStatusResponse]:
        pass

    @abstractmethod
    def mark_failed(self, run_id: str, error_message: str) -> Optional[GenerationJobStatusResponse]:
        pass

    @abstractmethod
    def mark_queued(self, run_id: str) -> Optional[GenerationJobStatusResponse]:
        """Reset one failed deterministic job so an idempotent retry can run it."""

    @abstractmethod
    def mark_superseded(
        self,
        run_id: str,
        replacement_run_id: str,
    ) -> Optional[GenerationJobStatusResponse]:
        """Keep a failed job for audit while hiding it behind its replacement."""

    def create_failed(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
        error_message: str,
        batch_id: str | None = None,
    ) -> Optional[GenerationJobStatusResponse]:
        """Persist a failed job after a larger continuation transaction rolls back.

        Standard repositories override this with a single atomic insert. The
        default keeps older custom repository implementations source-compatible.
        """
        self.create(
            run_id=run_id,
            learner_id=learner_id,
            topic=topic,
            knowledge_base_id=knowledge_base_id,
            request_payload=request_payload,
            batch_id=batch_id,
        )
        return self.mark_failed(run_id, error_message)

    @abstractmethod
    def fail_incomplete_before(self, before: datetime, error_message: str) -> list[str]:
        """Fail queued/running jobs left behind by an earlier process."""

    @abstractmethod
    def list_by_learner(self, learner_id: str) -> list[GenerationJobStatusResponse]:
        pass
