"""生成资源数据访问抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.learning_documents.schemas import LearningResource


class BaseResourceRepository(ABC):
    """生成资源仓库抽象基类"""

    @abstractmethod
    def get(self, resource_id: str) -> Optional[LearningResource]:
        """根据 ID 获取生成资源"""
        pass

    @abstractmethod
    def save(
        self,
        resource: LearningResource,
        learner_id: str,
        topic: str,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        generation_step_id: str | None = None,
    ) -> None:
        """保存或更新生成资源"""
        pass

    @abstractmethod
    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        """列出某学习者已发布的生成资源"""
        pass

    @abstractmethod
    def list_by_run(self, run_id: str) -> List[LearningResource]:
        """列出一次 Run 的全部资源版本，包括未发布版本。"""
        pass

    @abstractmethod
    def delete(self, resource_id: str) -> bool:
        """删除生成资源"""
        pass

    @abstractmethod
    def list_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
        batch_id: Optional[str] = None,
    ) -> List[LearningResource]:
        pass

    @abstractmethod
    def update_publication_decision(self, resource_id: str, *, publish: bool) -> Optional[LearningResource]:
        """Apply an authorized user publication decision."""
        pass

    def list_page_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[List[LearningResource], int]:
        """Return a deterministic published-resource page and total count."""
        resources = self.list_by_learner_with_filter(
            learner_id,
            resource_type,
            difficulty,
            run_id,
            batch_id,
        )
        return resources[offset : offset + limit], len(resources)

    @abstractmethod
    def save_spec(self, spec: ResourceSpecRecord) -> None:
        """Persist an immutable resource specification idempotently."""
        pass

    @abstractmethod
    def get_spec(self, resource_spec_id: str) -> Optional[ResourceSpecRecord]:
        pass

    @abstractmethod
    def list_specs_by_run(self, run_id: str) -> List[ResourceSpecRecord]:
        pass

    @abstractmethod
    def upsert_execution(self, execution: ResourceExecutionRecord) -> None:
        """Insert or advance the latest execution projection."""
        pass

    @abstractmethod
    def get_execution(
        self,
        run_id: str,
        resource_spec_id: str,
        representation: str,
    ) -> Optional[ResourceExecutionRecord]:
        pass

    @abstractmethod
    def get_execution_by_resource(self, resource_id: str) -> Optional[ResourceExecutionRecord]:
        pass

    @abstractmethod
    def list_executions_by_run(self, run_id: str) -> List[ResourceExecutionRecord]:
        pass
