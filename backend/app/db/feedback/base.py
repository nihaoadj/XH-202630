"""学习反馈数据访问抽象基类"""
from abc import ABC, abstractmethod
from typing import List, Optional

from app.models.schemas import FeedbackRecord


class BaseFeedbackRepository(ABC):
    """学习反馈仓库抽象基类"""

    @abstractmethod
    def get(self, feedback_id: str) -> Optional[FeedbackRecord]:
        """根据 ID 获取反馈记录"""
        pass

    @abstractmethod
    def save(self, record: FeedbackRecord) -> None:
        """保存反馈记录"""
        pass

    @abstractmethod
    def list_by_learner(self, learner_id: str) -> List[FeedbackRecord]:
        """列出某学习者的反馈记录"""
        pass
