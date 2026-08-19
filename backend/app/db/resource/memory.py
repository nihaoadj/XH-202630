"""内存实现的生成资源仓库"""
from typing import Dict, List, Optional

from app.db.resource.base import BaseResourceRepository
from app.models.schemas import LearningResource
from app.agents.validators import immutable_resource_payload
from app.db.audit.base import PersistenceConflict


class MemoryResourceRepository(BaseResourceRepository):
    """内存实现的生成资源仓库，用于开发与演示阶段"""

    def __init__(self):
        self._store: Dict[str, LearningResource] = {}
        self._learner_index: Dict[str, List[str]] = {}
        self.associations: Dict[str, Dict[str, str | None]] = {}

    def get(self, resource_id: str) -> Optional[LearningResource]:
        resource = self._store.get(resource_id)
        return resource.model_copy(deep=True) if resource else None

    def save(
        self,
        resource: LearningResource,
        learner_id: str,
        topic: str,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        generation_step_id: str | None = None,
    ) -> None:
        effective_run_id = run_id or resource.run_id
        effective_batch_id = batch_id or resource.batch_id or effective_run_id
        normalized = resource.model_copy(
            update={
                "learner_id": learner_id,
                "topic": topic,
                "run_id": effective_run_id,
                "batch_id": effective_batch_id,
            },
            deep=True,
        )
        existing = self._store.get(resource.resource_id)
        if existing and immutable_resource_payload(existing) != immutable_resource_payload(normalized):
            raise PersistenceConflict("resource immutable payload conflict")
        if effective_run_id is not None:
            for stored_id, association in self.associations.items():
                stored = self._store.get(stored_id)
                if (
                    stored is not None
                    and stored_id != resource.resource_id
                    and association.get("run_id") == effective_run_id
                    and stored.resource_type == normalized.resource_type
                    and stored.version == normalized.version
                ):
                    raise PersistenceConflict("duplicate resource version in run")
        self._store[resource.resource_id] = normalized
        if effective_run_id is not None or generation_step_id is not None:
            self.associations[resource.resource_id] = {
                "run_id": effective_run_id,
                "generation_step_id": generation_step_id,
            }
        if learner_id not in self._learner_index:
            self._learner_index[learner_id] = []
        if resource.resource_id not in self._learner_index[learner_id]:
            self._learner_index[learner_id].append(resource.resource_id)

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        resource_ids = self._learner_index.get(learner_id, [])
        return [
            self._store[rid].model_copy(deep=True)
            for rid in resource_ids
            if rid in self._store and self._store[rid].publication_status == "published"
        ]

    def list_by_run(self, run_id: str) -> List[LearningResource]:
        resources = [
            self._store[resource_id].model_copy(deep=True)
            for resource_id, association in self.associations.items()
            if association.get("run_id") == run_id and resource_id in self._store
        ]
        return sorted(resources, key=lambda item: (item.resource_type, item.version, item.resource_id))

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
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> List[LearningResource]:
        resources = self.list_by_learner(learner_id)
        return [
            resource
            for resource in resources
            if (resource_type is None or resource.resource_type == resource_type)
            and (difficulty is None or resource.difficulty == difficulty)
            and (run_id is None or getattr(resource, "run_id", None) == run_id)
        ]
