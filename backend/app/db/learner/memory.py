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
