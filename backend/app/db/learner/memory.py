from typing import Dict, Optional

from app.db.learner.base import BaseLearnerRepository
from app.models.schemas import LearnerProfile


class MemoryLearnerRepository(BaseLearnerRepository):
    """内存实现的学习者画像仓库，用于开发与演示阶段"""

    def __init__(self):
        self._store: Dict[str, LearnerProfile] = {}

    def get(self, learner_id: str) -> Optional[LearnerProfile]:
        return self._store.get(learner_id)

    def save(self, profile: LearnerProfile) -> None:
        self._store[profile.learner_id] = profile

    def delete(self, learner_id: str) -> bool:
        if learner_id in self._store:
            del self._store[learner_id]
            return True
        return False

    def list_all(self) -> Dict[str, LearnerProfile]:
        return self._store.copy()

    def update_partial(self, learner_id: str, updates: dict) -> Optional[LearnerProfile]:
        profile = self.get(learner_id)
        if profile is None:
            return None
        updated = profile.model_copy(update=updates)
        self.save(updated)
        return updated

    def list_with_pagination(
        self,
        page: int,
        page_size: int,
        skill_level: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> dict:
        items = sorted(self._store.values(), key=lambda profile: profile.learner_id)
        if user_id:
            items = [profile for profile in items if profile.user_id == user_id]
        if skill_level:
            items = [profile for profile in items if profile.skill_level == skill_level]
        total = len(items)
        start = (page - 1) * page_size
        return {"total": total, "page": page, "page_size": page_size, "items": items[start : start + page_size]}
