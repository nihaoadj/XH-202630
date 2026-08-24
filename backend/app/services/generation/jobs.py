from __future__ import annotations

import logging
import uuid

from app.db.generation.base import BaseGenerationJobRepository
from app.models.learning_documents.schemas import (
    GenerateRequest,
    GenerationJobCreateResponse,
    GenerationJobListResponse,
    GenerationJobStatusResponse,
    LearnerProfile,
)
from app.models.generation.progress import ResourceExecutionProgress, RunResourceProgressSummary
from app.services.generation.generation import GenerationService
from app.services.learners.mastery import MasteryService

logger = logging.getLogger(__name__)


class GenerationJobService:
    """Manage asynchronous generation jobs and execute them in the background."""

    def __init__(
        self,
        job_repo: BaseGenerationJobRepository,
        generation_service: GenerationService,
        mastery_service: MasteryService | None = None,
    ):
        self.job_repo = job_repo
        self.generation_service = generation_service
        self.mastery_service = mastery_service

    def create_job(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        retry_failed: bool = False,
    ) -> GenerationJobCreateResponse:
        run_id = run_id or str(uuid.uuid4())
        batch_id = batch_id or run_id
        knowledge_base_id = req.knowledge_base_id or learner.knowledge_base_id
        existing = self.job_repo.get(run_id)
        focus_snapshot = None
        if existing is None and self.mastery_service is not None:
            focus_snapshot = self.mastery_service.focus_snapshot(
                learner,
                mode=req.profile_focus_mode,
                explicit_node_ids=req.target_skill_nodes,
            )
            req.target_skill_nodes = list(focus_snapshot.adopted_node_ids)
            req.constraints = {
                **req.constraints,
                "learner_focus_snapshot": focus_snapshot.model_dump(mode="json"),
            }
        elif existing is not None:
            raw_snapshot = (existing.request_payload.get("constraints") or {}).get(
                "learner_focus_snapshot"
            )
            if raw_snapshot:
                from app.models.learners.mastery import LearnerFocusSnapshotV1
                focus_snapshot = LearnerFocusSnapshotV1.model_validate(raw_snapshot)
                req.target_skill_nodes = list(focus_snapshot.adopted_node_ids)
                req.constraints = {**req.constraints, "learner_focus_snapshot": raw_snapshot}
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
                batch_id=batch_id,
                learner_id=req.learner_id,
                topic=req.topic,
                knowledge_base_id=knowledge_base_id,
                request_payload=req.model_dump(mode="json"),
            )
            job_status = "queued"
        return GenerationJobCreateResponse(
            message="generation job accepted",
            run_id=run_id,
            batch_id=batch_id,
            learner_id=req.learner_id,
            topic=req.topic,
            knowledge_base_id=knowledge_base_id,
            job_status=job_status,
            focus_snapshot=focus_snapshot,
        )

    def get_job(self, run_id: str) -> GenerationJobStatusResponse | None:
        job = self.job_repo.get(run_id)
        return self._with_resource_progress(job) if job else None

    def _with_resource_progress(
        self, job: GenerationJobStatusResponse,
    ) -> GenerationJobStatusResponse:
        resource_repo = getattr(self.generation_service, "resource_repo", None)
        records = (
            resource_repo.list_executions_by_run(job.run_id)
            if resource_repo is not None
            else []
        )
        executions = []
        counts: dict[str, int] = {}
        for record in records:
            payload = record.model_dump(mode="python")
            payload["resource_execution_state"] = payload.pop("state")
            executions.append(ResourceExecutionProgress.model_validate(payload))
            counts[record.state] = counts.get(record.state, 0) + 1
        total = len(executions)
        terminal = sum(counts.get(item, 0) for item in ("approved", "human_review", "failed"))
        summary = RunResourceProgressSummary(
            total=total, counts=counts, approved=counts.get("approved", 0),
            human_review=counts.get("human_review", 0), failed=counts.get("failed", 0),
            # Approved execution rows are the public projection of resources
            # that passed the publication gate.
            published=counts.get("approved", 0),
            can_finalize=bool(total and terminal == total), items=executions)
        return job.model_copy(update={"resource_progress_summary": summary})

    def mark_superseded(self, run_id: str, replacement_run_id: str) -> GenerationJobStatusResponse | None:
        return self.job_repo.mark_superseded(run_id, replacement_run_id)

    def list_jobs(self, learner_id: str) -> GenerationJobListResponse:
        items = [self._with_resource_progress(item)
                 for item in self.job_repo.list_by_learner(learner_id)]
        return GenerationJobListResponse(
            learner_id=learner_id,
            total=len(items),
            items=items,
        )

    def run_job(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
        run_id: str,
        batch_id: str | None = None,
    ) -> None:
        self.job_repo.mark_running(run_id)
        try:
            job = self.job_repo.get(run_id)
            effective_batch_id = batch_id or (job.batch_id if job else run_id)
            response = self.generation_service.generate_with_run_id(
                learner,
                req,
                run_id=run_id,
                batch_id=effective_batch_id,
            )
            self.job_repo.mark_completed(
                run_id,
                [resource.resource_id for resource in response.resources],
            )
        except Exception as exc:
            logger.exception("Generation job failed run_id=%s", run_id)
            self.job_repo.mark_failed(run_id, str(exc))
