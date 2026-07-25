"""生成资源数据访问抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.models.schemas import LearningResource


class BaseResourceRepository(ABC):
    """生成资源仓库抽象基类"""

    @abstractmethod
    def get(self, resource_id: str) -> Optional[LearningResource]:
        """根据 ID 获取生成资源"""
        pass

    @abstractmethod
    def save(self, resource: LearningResource, learner_id: str, topic: str) -> None:
        """保存或更新生成资源"""
        pass

    @abstractmethod
    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        """列出某学习者的所有生成资源"""
        pass

    @abstractmethod
    def delete(self, resource_id: str) -> bool:
        """删除生成资源"""
        pass

    @abstractmethod
    def list_by_learner_with_filter(
        self, learner_id: str, resource_type: Optional[str] = None, difficulty: Optional[str] = None
    ) -> List[LearningResource]:
        pass
