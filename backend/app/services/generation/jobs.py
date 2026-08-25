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
from app.models.learning_documents.types import FEEDBACK_ONLY_RESOURCE_TYPES
from app.core.security.errors import ApplicationError, ErrorCode
from app.core.learning_tiers import TIER_POLICY_VERSION, difficulty_for_tier

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

    def _initial_generation_target(self, learner: LearnerProfile) -> list[str] | None:
        """Return the frozen initial-diagnosis target for the first batch.

        The initial placement decision is authoritative until the learner has
        a published resource.  Later batches intentionally fall back to the
        normal mastery/exposure recommendation policy.
        """
        if self.mastery_service is None:
            return None
        preferences = learner.learning_preferences
        metadata = preferences.metadata if preferences and isinstance(preferences.metadata, dict) else {}
        flow = metadata.get("initial_diagnostic_flow")
        if not isinstance(flow, dict) or flow.get("status") != "final":
            return None
        target = str(flow.get("initial_recommended_node_id") or "").strip()
        if not target:
            return None
        resource_repo = getattr(self.mastery_service, "resource_repo", None)
        published = (
            resource_repo.list_by_learner(learner.learner_id)
            if resource_repo is not None
            else []
        )
        if any(item.publication_status == "published" for item in published):
            return None
        return [target]

    def create_job(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        retry_failed: bool = False,
    ) -> GenerationJobCreateResponse:
        feedback_only = set(req.resource_types) & set(FEEDBACK_ONLY_RESOURCE_TYPES)
        if feedback_only and (
            req.resource_types != ["个性化纠错训练包"]
            or not isinstance(req.constraints.get("correction_focus_snapshot"), dict)
        ):
            raise ApplicationError(ErrorCode.FEEDBACK_ONLY_RESOURCE_TYPE, status_code=422)
        run_id = run_id or str(uuid.uuid4())
        batch_id = batch_id or run_id
        knowledge_base_id = req.knowledge_base_id or learner.knowledge_base_id
        existing = self.job_repo.get(run_id)
        created_new = False
        rescheduled_retry = False
        focus_snapshot = None
        if existing is None and self.mastery_service is not None:
            # The generic auto entry point must obey the same tier policy as a
            # feedback follow-up.  Do not let a three-node focus snapshot mix tiers.
            auto_targets = None
            if not req.target_skill_nodes and req.profile_focus_mode == "auto":
                auto_targets = self._initial_generation_target(learner)
                if auto_targets is None:
                    options = self.mastery_service.next_generation_options(learner)
                    # A generated request has no user-confirmed second choice.
                    # Keep later automatic generation on the product default
                    # of one current-tier node. Explicit entry points may
                    # still submit up to two nodes and are validated below.
                    auto_targets = list(options.recommended_node_ids[:1])
            focus_snapshot = self.mastery_service.focus_snapshot(
                learner,
                mode=req.profile_focus_mode,
                explicit_node_ids=req.target_skill_nodes,
            )
            if auto_targets is not None:
                # Keep the audit snapshot honestly labelled as an automatic
                # decision while replacing its adopted targets with the
                # tier-gated recommendation.
                focus_snapshot = focus_snapshot.model_copy(update={"adopted_node_ids": auto_targets})
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
        if self.mastery_service is not None and req.target_skill_nodes:
            try:
                tier = self.mastery_service.validate_generation_targets(learner, req.target_skill_nodes)
            except ValueError as exc:
                raise ApplicationError(ErrorCode.LEARNING_TIER_INVALID, status_code=422) from exc
            tier_options = self.mastery_service.next_generation_options(learner)
            expected_difficulty = difficulty_for_tier(int(tier))
            if req.difficulty_preference and req.difficulty_preference != expected_difficulty:
                raise ApplicationError(ErrorCode.LEARNING_TIER_INVALID, status_code=422)
            req.difficulty_preference = expected_difficulty
            req.constraints = {
                **req.constraints,
                "target_tier": tier,
                "target_skill_node_ids": list(req.target_skill_nodes),
                "tier_policy_version": TIER_POLICY_VERSION,
                "tier_progress_version": (
                    tier_options.tier_progress.row_version
                    if tier_options.tier_progress is not None
                    else learner.profile_version
                ),
            }
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
                rescheduled_retry = True
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
            created_new = True
        if (created_new or rescheduled_retry) and self.mastery_service is not None:
            self.mastery_service.schedule_generation(
                learner, run_id=run_id, selected_node_ids=req.target_skill_nodes,
            )
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
        published = 0
        for record in records:
            payload = record.model_dump(mode="python")
            payload["resource_execution_state"] = payload.pop("state")
            resource = (
                resource_repo.get(record.resource_id)
                if record.resource_id
                else None
            )
            payload["publication_status"] = (
                resource.publication_status if resource is not None else "unpublished"
            )
            if payload["publication_status"] == "published":
                published += 1
            executions.append(ResourceExecutionProgress.model_validate(payload))
            counts[record.state] = counts.get(record.state, 0) + 1
        total = len(executions)
        terminal = sum(counts.get(item, 0) for item in ("approved", "human_review", "failed"))
        summary = RunResourceProgressSummary(
            total=total, counts=counts, approved=counts.get("approved", 0),
            human_review=counts.get("human_review", 0), failed=counts.get("failed", 0),
            # Review approval and publication are distinct gates.  A resource
            # can be approved while Claim extraction is still in progress.
            published=published,
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
            if self.mastery_service is not None:
                self.mastery_service.release_failed_generation(learner, run_id=run_id)
