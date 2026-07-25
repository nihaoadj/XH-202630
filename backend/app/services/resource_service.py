from typing import List

from app.db.resource.base import BaseResourceRepository
from app.models.schemas import LearningResource


class ResourceService:
    """生成资源业务服务"""

    def __init__(self, repo: BaseResourceRepository):
        self.repo = repo

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        """查询学习者生成资源历史"""
        return self.repo.list_by_learner(learner_id)

    def get(self, resource_id: str) -> LearningResource | None:
        return self.repo.get(resource_id)

    def list_by_learner_with_filter(
        self, learner_id: str, resource_type: str | None = None, difficulty: str | None = None
    ) -> List[LearningResource]:
        return self.repo.list_by_learner_with_filter(learner_id, resource_type, difficulty)
