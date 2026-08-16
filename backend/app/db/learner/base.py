from abc import ABC, abstractmethod
from typing import Dict, Optional

from app.models.schemas import LearnerProfile


class BaseLearnerRepository(ABC):
    """学习者画像数据访问抽象基类"""

    @abstractmethod
    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        """根据 ID 获取学习者画像"""
        pass

    @abstractmethod
    def save(self, profile: LearnerProfile) -> None:
        """保存或更新学习者画像"""
        pass

    @abstractmethod
    def delete(self, learner_id: str) -> bool:
        """删除学习者画像"""
        pass

    @abstractmethod
    def list_all(self) -> Dict[str, LearnerProfile]:
        """列出所有学习者画像"""
        pass

    @abstractmethod
    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        pass

    @abstractmethod
    def list_with_pagination(
        self,
        page: int,
        page_size: int,
        skill_level: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        pass
