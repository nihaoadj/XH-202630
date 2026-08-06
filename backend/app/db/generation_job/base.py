"""异步生成任务仓储接口定义。"""
from abc import ABC, abstractmethod
from typing import Any, Optional

from app.models.schemas import GenerationJobStatusResponse


class BaseGenerationJobRepository(ABC):
    @abstractmethod
    def create(
        self,
        run_id: str,
        learner_id: str,
        topic: str,
        knowledge_base_id: Optional[str],
        request_payload: dict[str, Any],
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
    def list_by_learner(self, learner_id: str) -> list[GenerationJobStatusResponse]:
        pass
