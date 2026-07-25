from abc import ABC, abstractmethod
from typing import Any, Iterable, Optional

from app.models.schemas import ReviewSummary


class BaseAuditRepository(ABC):
    """持久化 Agent 过程与资源审核结果的抽象接口。"""

    @abstractmethod
    def save_run(
        self,
        learner_id: str,
        knowledge_base_id: Optional[str],
        topic: str,
        trace: Iterable[dict[str, Any]],
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        status: str,
    ) -> str:
        pass

    @abstractmethod
    def save_review(self, resource_id: str, review: dict[str, Any], run_id: Optional[str]) -> str:
        pass

    @abstractmethod
    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        """获取资源最近一次审核及其 Claim 证据。"""
