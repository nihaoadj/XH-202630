"""内存实现的生成资源仓库"""
from typing import Dict, List, Optional

from app.db.resource.base import BaseResourceRepository
from app.db.resource.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.schemas import LearningResource
from app.agents.validators import immutable_resource_payload
from app.db.audit.base import PersistenceConflict


class MemoryResourceRepository(BaseResourceRepository):
    """内存实现的生成资源仓库，用于开发与演示阶段"""

    def __init__(self):
        self._store: Dict[str, LearningResource] = {}
        self._learner_index: Dict[str, List[str]] = {}
        self.associations: Dict[str, Dict[str, str | None]] = {}
        self._specs: Dict[str, ResourceSpecRecord] = {}
        self._executions: Dict[tuple[str, str, str], ResourceExecutionRecord] = {}

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
                if stored is None:
                    continue
                same_identity = (
                    stored.resource_spec_id == normalized.resource_spec_id
                    and stored.representation == normalized.representation
                    if normalized.resource_spec_id is not None
                    else stored.resource_spec_id is None
                    and stored.resource_type == normalized.resource_type
                )
                if (
                    stored_id != resource.resource_id
                    and association.get("run_id") == effective_run_id
                    and same_identity
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

    def list_page_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: Optional[str] = None,
        difficulty: Optional[str] = None,
        run_id: Optional[str] = None,
        *,
        offset: int = 0,
        limit: int = 20,
    ) -> tuple[List[LearningResource], int]:
        resources = self.list_by_learner_with_filter(
            learner_id,
            resource_type,
            difficulty,
            run_id,
        )
        return resources[offset : offset + limit], len(resources)

    def save_spec(self, spec: ResourceSpecRecord) -> None:
        existing = self._specs.get(spec.resource_spec_id)
        if existing is not None:
            existing_payload = existing.model_dump(exclude={"created_at"})
            incoming_payload = spec.model_dump(exclude={"created_at"})
            if existing_payload != incoming_payload:
                raise PersistenceConflict("resource spec immutable payload conflict")
            return
        for stored in self._specs.values():
            if stored.run_id == spec.run_id and stored.resource_type == spec.resource_type:
                raise PersistenceConflict("duplicate resource type in run specs")
        self._specs[spec.resource_spec_id] = spec.model_copy(deep=True)

    def get_spec(self, resource_spec_id: str) -> Optional[ResourceSpecRecord]:
        spec = self._specs.get(resource_spec_id)
        return spec.model_copy(deep=True) if spec else None

    def list_specs_by_run(self, run_id: str) -> List[ResourceSpecRecord]:
        return sorted(
            (
                spec.model_copy(deep=True)
                for spec in self._specs.values()
                if spec.run_id == run_id
            ),
            key=lambda item: (item.display_order, item.resource_spec_id),
        )

    def upsert_execution(self, execution: ResourceExecutionRecord) -> None:
        key = (execution.run_id, execution.resource_spec_id, execution.representation)
        existing = self._executions.get(key)
        if existing is not None:
            immutable_fields = (
                "execution_id",
                "run_id",
                "resource_spec_id",
                "resource_type",
                "representation",
                "agent_name",
                "prompt_version",
                "artifact_format",
            )
            if any(getattr(existing, field) != getattr(execution, field) for field in immutable_fields):
                raise PersistenceConflict("resource execution identity conflict")
            if execution.attempt < existing.attempt:
                raise PersistenceConflict("resource execution attempt regression")
        self._executions[key] = execution.model_copy(deep=True)

    def get_execution(
        self,
        run_id: str,
        resource_spec_id: str,
        representation: str,
    ) -> Optional[ResourceExecutionRecord]:
        execution = self._executions.get((run_id, resource_spec_id, representation))
        return execution.model_copy(deep=True) if execution else None

    def get_execution_by_resource(self, resource_id: str) -> Optional[ResourceExecutionRecord]:
        execution = next(
            (item for item in self._executions.values() if item.resource_id == resource_id),
            None,
        )
        return execution.model_copy(deep=True) if execution else None

    def list_executions_by_run(self, run_id: str) -> List[ResourceExecutionRecord]:
        return sorted(
            (
                execution.model_copy(deep=True)
                for execution in self._executions.values()
                if execution.run_id == run_id
            ),
            key=lambda item: (item.resource_spec_id, item.representation),
        )
