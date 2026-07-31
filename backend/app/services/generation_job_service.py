from __future__ import annotations

import logging
import uuid

from app.db.generation_job.base import BaseGenerationJobRepository
from app.models.schemas import (
    GenerateRequest,
    GenerationJobCreateResponse,
    GenerationJobStatusResponse,
    LearnerProfile,
)
from app.services.generation_service import GenerationService

logger = logging.getLogger(__name__)


class GenerationJobService:
    """Manage asynchronous generation jobs and execute them in the background."""

    def __init__(
        self,
        job_repo: BaseGenerationJobRepository,
        generation_service: GenerationService,
    ):
        self.job_repo = job_repo
        self.generation_service = generation_service

    def create_job(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
    ) -> GenerationJobCreateResponse:
        run_id = str(uuid.uuid4())
        knowledge_base_id = req.knowledge_base_id or learner.knowledge_base_id
        self.job_repo.create(
            run_id=run_id,
            learner_id=req.learner_id,
            topic=req.topic,
            knowledge_base_id=knowledge_base_id,
            request_payload=req.model_dump(mode="json"),
        )
        return GenerationJobCreateResponse(
            message="generation job accepted",
            run_id=run_id,
            learner_id=req.learner_id,
            topic=req.topic,
            knowledge_base_id=knowledge_base_id,
            job_status="queued",
        )

    def get_job(self, run_id: str) -> GenerationJobStatusResponse | None:
        return self.job_repo.get(run_id)

    def run_job(self, learner: LearnerProfile, req: GenerateRequest, run_id: str) -> None:
        self.job_repo.mark_running(run_id)
        try:
            response = self.generation_service.generate_with_run_id(learner, req, run_id=run_id)
            self.job_repo.mark_completed(
                run_id,
                [resource.resource_id for resource in response.resources],
            )
        except Exception as exc:
            logger.exception("Generation job failed run_id=%s", run_id)
            self.job_repo.mark_failed(run_id, str(exc))
