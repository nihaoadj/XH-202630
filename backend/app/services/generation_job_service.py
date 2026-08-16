from __future__ import annotations

import logging
import uuid

from app.db.generation_job.base import BaseGenerationJobRepository
from app.models.schemas import (
    GenerateRequest,
    GenerationJobCreateResponse,
    GenerationJobListResponse,
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
        *,
        run_id: str | None = None,
        retry_failed: bool = False,
    ) -> GenerationJobCreateResponse:
        run_id = run_id or str(uuid.uuid4())
        knowledge_base_id = req.knowledge_base_id or learner.knowledge_base_id
        existing = self.job_repo.get(run_id)
        if existing is not None:
            if (
                existing.learner_id != req.learner_id
                or existing.topic != req.topic
                or existing.knowledge_base_id != knowledge_base_id
            ):
                raise ValueError("run_id already belongs to another generation request")
            if existing.job_status == "failed" and retry_failed:
                requeued = self.job_repo.mark_queued(run_id)
                if requeued is None:
                    raise ValueError("generation job disappeared during retry")
                existing = requeued
            job_status = existing.job_status
        else:
            self.job_repo.create(
                run_id=run_id,
                learner_id=req.learner_id,
                topic=req.topic,
                knowledge_base_id=knowledge_base_id,
                request_payload=req.model_dump(mode="json"),
            )
            job_status = "queued"
        return GenerationJobCreateResponse(
            message="generation job accepted",
            run_id=run_id,
            learner_id=req.learner_id,
            topic=req.topic,
            knowledge_base_id=knowledge_base_id,
            job_status=job_status,
        )

    def get_job(self, run_id: str) -> GenerationJobStatusResponse | None:
        return self.job_repo.get(run_id)

    def list_jobs(self, learner_id: str) -> GenerationJobListResponse:
        items = self.job_repo.list_by_learner(learner_id)
        return GenerationJobListResponse(
            learner_id=learner_id,
            total=len(items),
            items=items,
        )

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
