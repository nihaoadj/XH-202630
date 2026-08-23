"""Application facade for the interactive-courseware resource domain."""

from __future__ import annotations

from typing import Any

from app.agents.resource_workflows.interactive_courseware.workflow import (
    InteractiveCoursewareWorkflow,
)
from app.db.audit.base import BaseAuditRepository
from app.core.storage.file_storage import load_resource_file
from app.models.courseware import (
    CoursewareJobCreateRequest,
    CoursewareJobDetail,
    CoursewareJobResponse,
    CoursewareResourceDetail,
)
from app.models.shared.resource_library import ResourceLibraryItem
from app.services.learning_documents.resources import ResourceService
from app.services.courseware.source import CoursewareAdmissionError
from app.agents.resource_workflows.interactive_courseware.scene_composer_agent import (
    compose_courseware_scene,
)


class CoursewareService:
    """Coordinate dependencies and expose the HTTP-facing courseware facade.

    Generation nodes, prompts, model calls, validation and artifact production
    belong to :class:`InteractiveCoursewareWorkflow`; this class only wires
    the workflow and delegates task/query/publication operations.
    """

    def __init__(
        self,
        repo,
        resource_service: ResourceService,
        audit_repo: BaseAuditRepository,
        llm_gateway: Any | None = None,
        workflow: InteractiveCoursewareWorkflow | None = None,
        learner_context_provider: Any | None = None,
    ):
        self.repo = repo
        self.resource_service = resource_service
        self.audit_repo = audit_repo
        self.llm_gateway = llm_gateway
        self.workflow = workflow or InteractiveCoursewareWorkflow(
            repo,
            resource_service,
            audit_repo,
            llm_gateway,
            learner_context_provider=learner_context_provider,
        )
        # Preserve the existing integration seam while the loader remains a
        # dependency of the workflow instead of service business logic.
        self.workflow.file_loader = load_resource_file
        # Resolve the provider through this module so existing integration
        # seams can be replaced without moving orchestration back into service.
        self.workflow.scene_composer = lambda *args, **kwargs: compose_courseware_scene(*args, **kwargs)

    def create_job(self, request: CoursewareJobCreateRequest) -> CoursewareJobResponse:
        return self.workflow.create_job(request)

    def get_job(self, run_id: str) -> CoursewareJobResponse | None:
        return self.workflow.get_job(run_id)

    def get_job_detail(self, run_id: str) -> CoursewareJobDetail | None:
        return self.workflow.get_job_detail(run_id)

    def events(self, run_id: str, after_sequence: int = 0) -> list[dict[str, Any]]:
        return self.workflow.events(run_id, after_sequence)

    def run_job(self, run_id: str) -> CoursewareJobResponse | None:
        return self.workflow.run(run_id)

    def retry(self, run_id: str) -> CoursewareJobResponse | None:
        return self.workflow.retry(run_id)

    def cancel(self, run_id: str) -> CoursewareJobResponse | None:
        return self.workflow.cancel(run_id)

    def retry_scene(self, run_id: str, scene_id: str, *, enqueue_only: bool = False) -> CoursewareJobResponse | None:
        return self.workflow.retry_scene(run_id, scene_id, enqueue_only=enqueue_only)

    def process_scene_outbox(self, run_id: str | None = None, limit: int = 10) -> dict[str, int]:
        return self.workflow.process_scene_outbox(run_id=run_id, limit=limit)

    def publish(self, run_id: str) -> CoursewareJobResponse | None:
        return self.workflow.publish(run_id)

    def get_resource(self, resource_id: str) -> CoursewareResourceDetail | None:
        return self.workflow.get_resource(resource_id)

    def artifact(self, resource_id: str) -> tuple[dict[str, Any], bytes] | None:
        return self.workflow.artifact(resource_id)

    def packaged_artifact(
        self,
        resource_id: str,
        package_format: str,
    ) -> tuple[dict[str, Any], bytes] | None:
        return self.workflow.packaged_artifact(resource_id, package_format)

    def list_library_items(self, learner_id: str) -> list[ResourceLibraryItem]:
        return self.workflow.list_library_items(learner_id)

    def ingest_learning_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.repo.ingest_learning_events(events)

    def learning_progress(self, resource_id: str, release_id: str) -> dict[str, Any]:
        return self.repo.learning_progress(resource_id=resource_id, release_id=release_id)
