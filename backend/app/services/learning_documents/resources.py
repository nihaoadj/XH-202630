from typing import List

from app.db.learning_documents.base import BaseResourceRepository
from app.models.learning_documents.schemas import LearningResource, ResourceDetail
from app.models.generation.progress import ResourceExecutionProgress


class ResourceService:
    """生成资源业务服务"""

    def __init__(self, repo: BaseResourceRepository):
        self.repo = repo

    def list_by_learner(self, learner_id: str) -> List[LearningResource]:
        """查询学习者生成资源历史"""
        return self.repo.list_by_learner(learner_id)

    def get(self, resource_id: str) -> LearningResource | None:
        return self.repo.get(resource_id)

    def update_publication_decision(self, resource_id: str, *, publish: bool) -> LearningResource | None:
        return self.repo.update_publication_decision(resource_id, publish=publish)

    def list_by_learner_with_filter(
        self,
        learner_id: str,
        resource_type: str | None = None,
        difficulty: str | None = None,
        run_id: str | None = None,
        batch_id: str | None = None,
    ) -> List[LearningResource]:
        return self.repo.list_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id)

    def list_page_by_learner_with_filter(
        self, learner_id: str, resource_type: str | None = None,
        difficulty: str | None = None, run_id: str | None = None, batch_id: str | None = None,
        *, page: int = 1, page_size: int = 20,
    ) -> tuple[List[LearningResource], int]:
        return self.repo.list_page_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id,
            offset=(page - 1) * page_size, limit=page_size)

    def get_published_detail(self, resource_id: str) -> ResourceDetail | None:
        resource = self.repo.get(resource_id)
        if resource is None or resource.publication_status != "published":
            return None
        execution = self.repo.get_execution_by_resource(resource_id)
        progress = None
        if execution is not None:
            payload = execution.model_dump(mode="python")
            payload["resource_execution_state"] = payload.pop("state")
            progress = ResourceExecutionProgress.model_validate(payload)
        return ResourceDetail(
            **resource.model_dump(mode="python"), status="published", is_published=True,
            execution=progress,
            metadata={
                "agent_name": execution.agent_name if execution else None,
                "prompt_version": execution.prompt_version if execution else None,
                "artifact_format": execution.artifact_format if execution else None,
                "validation_status": execution.validation_status if execution else None,
            },
            review_summary={"review_id": resource.review_id,
                            "review_status": resource.review_status,
                            "claim_count": resource.claim_count},
        )
