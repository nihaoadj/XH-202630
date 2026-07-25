from typing import Optional

from app.db.learner.base import BaseLearnerRepository
from app.models.schemas import LearnerProfile


class LearnerService:
    """学习者画像业务服务
    
    通过构造函数注入Repository依赖。
    """

    def __init__(self, repo: BaseLearnerRepository):
        """初始化服务
        
        Args:
            repo: 学习者画像仓库（通过DI容器注入）
        """
        self.repo = repo

    def create_or_update(self, profile: LearnerProfile) -> LearnerProfile:
        """创建或更新学习者画像"""
        self.repo.save(profile)
        return profile

    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        """获取学习者画像"""
        return self.repo.get(learner_id)

    def delete(self, learner_id: str) -> bool:
        """删除学习者画像"""
        return self.repo.delete(learner_id)

    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        return self.repo.update_partial(learner_id, updates)

    def list_with_pagination(self, page: int, page_size: int, skill_level: Optional[str] = None) -> dict:
        return self.repo.list_with_pagination(page, page_size, skill_level)
