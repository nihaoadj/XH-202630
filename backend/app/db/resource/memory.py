"""内存实现的生成资源仓库"""
from typing import Dict, List, Optional

from app.db.resource.base import BaseResourceRepository
from app.models.schemas import LearningResource


class MemoryResourceRepository(BaseResourceRepository):
    """内存实现的生成资源仓库，用于开发与演示阶段"""

    def __init__(self):
        self._store: Dict[str, LearningResource] = {}
        self._learner_index: Dict[str, List[str]] = {}
        self.associations: Dict[str, Dict[str, str | None]] = {}

    def get(self, resource_id: str) -> Optional[LearningResource]:
        return self._store.get(resource_id)

    def save(
        self,
        resource: LearningResource,
        learner_id: str,
        topic: str,
        *,
        run_id: str | None = None,
        generation_step_id: str | None = None,
    ) -> None:
        self._store[resource.resource_id] = resource
        if run_id is not None or generation_step_id is not None:
            self.associations[resource.resource_id] = {
                "run_id": run_id,
                "generation_step_id": generation_step_id,
            }
        if learner_id not in self._learner_index:
            self._learner_index[learner_id] = []
        if resource.resource_id not in self._learner_index[learner_id]:
            self._learner_index[learner_id].append(resource.resource_id)

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        resource_ids = self._learner_index.get(learner_id, [])
        return [self._store[rid] for rid in resource_ids if rid in self._store]

    def delete(self, resource_id: str) -> bool:
        if resource_id in self._store:
            resource = self._store.pop(resource_id)
            self.associations.pop(resource_id, None)
            learner_ids = list(self._learner_index.keys())
            for learner_id in learner_ids:
                if resource_id in self._learner_index[learner_id]:
                    self._learner_index[learner_id].remove(resource_id)
            return True
        return False

    def list_by_learner_with_filter(
        self, learner_id: str, resource_type: Optional[str] = None, difficulty: Optional[str] = None
    ) -> List[LearningResource]:
        resources = self.list_by_learner(learner_id)
        return [
            resource
            for resource in resources
            if (resource_type is None or resource.resource_type == resource_type)
            and (difficulty is None or resource.difficulty == difficulty)
        ]
