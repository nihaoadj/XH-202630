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
