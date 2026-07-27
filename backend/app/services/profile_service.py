from typing import Optional

from app.db.learner.base import BaseLearnerRepository
from app.models.schemas import LearnerProfile


class ProfileService:
    """学习者画像查询与维护服务。

    首次创建画像由 OnboardingService 根据问卷完成；本服务只负责已存在画像的查询、维护和删除。
    """

    def __init__(self, repo: BaseLearnerRepository):
        """初始化服务
        
        Args:
            repo: 学习者画像仓库（通过DI容器注入）
        """
        self.repo = repo

    def save_existing_profile(self, profile: LearnerProfile) -> Optional[LearnerProfile]:
        """保存已存在画像的系统更新，不承担首次创建职责。"""
        if self.repo.get(profile.learner_id) is None:
            return None
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
