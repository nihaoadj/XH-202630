from __future__ import annotations

from collections.abc import Callable

import logging
import uuid

from app.db.generation.base import BaseGenerationJobRepository
from app.core.execution import ExecutionFence, execution_fence
from app.models.generation.dispatch import TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION
from app.models.generation.resource_retry import ResourceRetryContext
from app.services.generation.resource_retry import prepare_resource_retry
from app.services.generation.dispatch import submission_identity
from app.models.shared.persistence import canonical_hash
from app.db.generation.fencing import ExecutionLeaseLost
from app.db.shared.retry import run_with_sqlite_retry
from sqlalchemy.exc import IntegrityError
from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.services.learning_documents.resources import ResourceService
from app.services.generation.continuation import (
    create_continuation,
    execute_continuation,
    prepare_continuation,
)
from app.services.generation.continuation_uow import (
    ContinuationAtomicityError,
    ContinuationUnitOfWork,
    has_standard_core_writers,
    has_standard_writers,
)
from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
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
from app.models.feedback.feedback_loop import LearningIntent
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
        dispatch_mode: str = "background",
    ):
        self.job_repo = job_repo
        self.generation_service = generation_service
        self.mastery_service = mastery_service
        self.dispatch_mode = dispatch_mode

    def create_continuation(
        self,
        learner: LearnerProfile,
        batch_id: str,
        payload: ContinueResourceBatchRequest,
        *,
        resource_service_factory: Callable[[], ResourceService],
        feedback_repo_factory: Callable[[], BaseFeedbackLoopRepository],
        run_id: str | None = None, submission_hash: str | None = None,
    ) -> tuple[GenerationJobCreateResponse, GenerateRequest]:
        """Prepare a continuation; the API schedules the returned request last."""
        if run_id and submission_hash:
            found = self._existing_submission(run_id, submission_hash)
            if found:
                return found, GenerateRequest.model_validate(self.job_repo.get(run_id).request_payload)
        # Preserve lightweight stubs with custom mutation methods only when
        # they have no standard persistence graph. Such a path retains legacy
        # behavior and makes no transactional-atomicity claim.
        custom_mutator = any(
            getattr(getattr(self, name), "__func__", getattr(self, name))
            is not getattr(GenerationJobService, name)
            for name in ("create_job", "mark_superseded")
        )
        if custom_mutator and has_standard_core_writers(self):
            raise ContinuationAtomicityError(
                "custom continuation mutators cannot use standard repositories"
            )
        if custom_mutator:
            return create_continuation(
                self, learner, batch_id, payload,
                resource_service_factory=resource_service_factory,
                feedback_repo_factory=feedback_repo_factory,
            )

        prepared = prepare_continuation(
            self,
            learner,
            batch_id,
            payload,
            resource_service_factory=resource_service_factory,
        )
        feedback_repositories = [
            feedback_repo_factory()
            for _ in range(prepared.feedback_repo_call_count)
        ]
        repository_index = 0

        def planned_feedback_repo_factory():
            nonlocal repository_index
            if repository_index >= len(feedback_repositories):
                raise RuntimeError("continuation requested an unplanned feedback repository")
            repository = feedback_repositories[repository_index]
            repository_index += 1
            return repository

        # Unknown custom repositories retain their legacy direct behavior when
        # no standard participant is present. Once any standard writer is in
        # the graph, the UOW validates every writer before the first mutation.
        if not has_standard_writers(self, feedback_repositories):
            return execute_continuation(
                prepared,
                self,
                learner,
                feedback_repo_factory=planned_feedback_repo_factory,
            )

        run_id = run_id or str(uuid.uuid4())
        uow = ContinuationUnitOfWork(self, feedback_repositories)
        try:
            with uow:
                result = execute_continuation(
                    prepared,
                    uow.generation_job_service,
                    learner,
                    feedback_repo_factory=uow.feedback_repo_factory,
                    run_id=run_id, submission_hash=submission_hash,
                )
        except Exception:
            if uow.schedule_failed:
                request = prepared.generation_request
                knowledge_base_id = request.knowledge_base_id or learner.knowledge_base_id
                if self.job_repo.get(run_id) is None:
                    self.job_repo.create_failed(
                        run_id=run_id,
                        batch_id=prepared.batch_id,
                        learner_id=request.learner_id,
                        topic=request.topic,
                        knowledge_base_id=knowledge_base_id,
                        request_payload=request.model_dump(mode="json"),
                        error_message="CURRICULUM_SCHEDULE_FAILED",
                    )
            raise
        return result

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

    @property
    def durable_dispatch(self) -> bool:
        return self.dispatch_mode == "worker" and bool(getattr(self.job_repo, "supports_durable_dispatch", False))

    def _existing_submission(self, run_id, submission_hash):
        job = self.job_repo.get(run_id)
        if job is None:
            return None
        metadata = self.job_repo.get_dispatch(run_id) if hasattr(self.job_repo, "get_dispatch") else {}
        if not metadata or metadata.get("submission_hash") != submission_hash:
            raise ApplicationError(ErrorCode.GENERATION_IDEMPOTENCY_CONFLICT, status_code=409)
        return GenerationJobCreateResponse(message="generation job accepted", run_id=job.run_id,
            batch_id=job.batch_id or job.run_id, learner_id=job.learner_id, topic=job.topic,
            knowledge_base_id=job.knowledge_base_id, job_status=job.job_status, focus_snapshot=job.focus_snapshot)

    def create_resource_retry(self, learner, source_run_id, spec_id, representation, *, idempotency_key=None):
        context = prepare_resource_retry(self, learner, source_run_id, spec_id, representation)
        identity = submission_identity(
            learner, context, idempotency_key if idempotency_key is not None else context.context_hash,
            f"resource-retry:{source_run_id}:{spec_id}:{representation}",
        )
        source = self.job_repo.get(source_run_id)
        job = self.create_job(context.learner, context.request.model_copy(deep=True),
                              batch_id=source.batch_id or source_run_id,
                              resource_retry_context=context.model_dump(mode="json"), **identity)
        return job, context.request

    def create_job(self, learner, req, *, run_id=None, batch_id=None, retry_failed=False, submission_hash=None,
                   resource_retry_context=None):
        if run_id and submission_hash and not retry_failed:
            found = self._existing_submission(run_id, submission_hash)
            if found:
                return found
        if self.durable_dispatch and not getattr(self, "_continuation_atomicity_active", False):
            def atomic_create():
                if run_id and submission_hash and not retry_failed:
                    found = self._existing_submission(run_id, submission_hash)
                    if found:
                        return found
                with ContinuationUnitOfWork(self, []) as uow:
                    return uow.generation_job_service._create_job(
                        learner, req.model_copy(deep=True), run_id=run_id, batch_id=batch_id,
                        retry_failed=retry_failed, submission_hash=submission_hash,
                        resource_retry_context=resource_retry_context,
                    )
            try:
                return run_with_sqlite_retry(atomic_create)
            except IntegrityError:
                if run_id and self.job_repo.get(run_id) is not None:
                    return run_with_sqlite_retry(atomic_create)
                raise
        return self._create_job(learner, req, run_id=run_id, batch_id=batch_id,
                                retry_failed=retry_failed, submission_hash=submission_hash,
                                resource_retry_context=resource_retry_context)

    def _create_job(
        self,
        learner: LearnerProfile,
        req: GenerateRequest,
        *,
        run_id: str | None = None,
        batch_id: str | None = None,
        retry_failed: bool = False,
        submission_hash: str | None = None,
        resource_retry_context: dict | None = None,
    ) -> GenerationJobCreateResponse:
        feedback_only = set(req.resource_types) & set(FEEDBACK_ONLY_RESOURCE_TYPES)
        correction_followup = (
            "个性化纠错训练包" in req.resource_types
            and isinstance(req.constraints.get("correction_focus_snapshot"), dict)
        )
        selection_type = req.constraints.get("selection_type") if isinstance(req.constraints, dict) else None
        if feedback_only and (
            not correction_followup
        ):
            raise ApplicationError(ErrorCode.FEEDBACK_ONLY_RESOURCE_TYPE, status_code=422)
        run_id = run_id or str(uuid.uuid4())
        batch_id = batch_id or run_id
        knowledge_base_id = req.knowledge_base_id or learner.knowledge_base_id
        existing = self.job_repo.get(run_id)
        if retry_failed:
            seen = set()
            while existing and existing.superseded_by_run_id:
                if existing.run_id in seen:
                    raise ValueError("generation retry lineage contains a cycle")
                seen.add(existing.run_id)
                run_id = existing.superseded_by_run_id
                existing = self.job_repo.get(run_id)
        if existing and submission_hash and hasattr(self.job_repo, "get_dispatch"):
            stored = self.job_repo.get_dispatch(run_id) or {}
            legacy_retry = (retry_failed and existing.job_status == "failed"
                            and stored.get("dispatch_mode") == "legacy" and not stored.get("submission_hash"))
            if stored.get("submission_hash") != submission_hash and not legacy_retry:
                raise ApplicationError(ErrorCode.GENERATION_IDEMPOTENCY_CONFLICT, status_code=409)
        created_new = False
        rescheduled_retry = False
        focus_snapshot = None
        if existing is None and self.mastery_service is not None and resource_retry_context is None:
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
            if auto_targets is not None and not auto_targets:
                # No recommendation must not silently turn into an unscoped
                # planner request. Use the first node from the same frozen
                # auto snapshot when available; otherwise make the caller
                # choose a node explicitly instead of expanding weak points
                # into several resource targets.
                auto_targets = list(focus_snapshot.adopted_node_ids[:1])
            if auto_targets is not None and not auto_targets:
                raise ApplicationError(
                    ErrorCode.LEARNING_TIER_INVALID,
                    public_message="当前没有可自动选择的学习节点，请先手动选择一个节点",
                    status_code=422,
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
        if self.mastery_service is not None and req.target_skill_nodes and resource_retry_context is None:
            try:
                if correction_followup:
                    tier = self.mastery_service.validate_correction_targets(
                        learner,
                        req.target_skill_nodes,
                        req.constraints["correction_focus_snapshot"],
                    )
                elif selection_type in {"lower_tier_selection", "cross_tier_prerequisite_review"}:
                    intent = (
                        LearningIntent.DOWNGRADE_LEARNING
                        if selection_type == "lower_tier_selection"
                        else LearningIntent.LEARN_NEW_AND_REINFORCE
                    )
                    tier = self.mastery_service.classify_generation_selection(
                        learner, req.target_skill_nodes, intent=intent,
                    )[1]
                else:
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
                audit = getattr(self.generation_service, "audit_repo", None)
                prior_run = audit.get_run(run_id) if audit is not None else None
                if self.durable_dispatch or (prior_run and prior_run.status.value in {"failed", "interrupted"}):
                    parent_id = run_id
                    retry_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"generation-retry:{parent_id}"))
                    if not hasattr(self.job_repo, "create_retry"):
                        raise ApplicationError(ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT, status_code=409)
                    run_id = self.job_repo.create_retry(parent_id, run_id=retry_id,
                        learner_id=req.learner_id, topic=req.topic, knowledge_base_id=knowledge_base_id,
                        request_payload=req.model_dump(mode="json"), batch_id=batch_id,
                        dispatch_snapshot=self._dispatch_snapshot(learner, req) if self.durable_dispatch else None,
                        submission_hash=submission_hash)
                    existing = self.job_repo.get(run_id)
                else:
                    existing = self.job_repo.mark_queued(run_id)
                if existing is None:
                    raise ValueError("generation job disappeared during retry")
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
                **({"dispatch_snapshot": self._dispatch_snapshot(learner, req, resource_retry_context),
                    "submission_hash": submission_hash} if self.durable_dispatch or resource_retry_context is not None else
                   {"submission_hash": submission_hash} if submission_hash and hasattr(self.job_repo, "get_dispatch") else {}),
            )
            job_status = "queued"
            created_new = True
        if (created_new or rescheduled_retry) and self.mastery_service is not None:
            try:
                self.mastery_service.schedule_generation(
                    learner, run_id=run_id, selected_node_ids=req.target_skill_nodes,
                    selection_type=selection_type,
                )
            except Exception:
                if getattr(self, "_continuation_atomicity_active", False):
                    self._continuation_schedule_failed = True
                self.job_repo.mark_failed(run_id, "CURRICULUM_SCHEDULE_FAILED")
                self.mastery_service.release_failed_generation(learner, run_id=run_id)
                raise
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

    @staticmethod
    def _dispatch_snapshot(learner, request, resource_retry_context=None):
        snapshot = {"workflow_version": TEXT_WORKFLOW_VERSION, "learner": learner.model_dump(mode="json"),
                    "request_hash": canonical_hash(request.model_dump(mode="json"))}
        if resource_retry_context is not None:
            context = ResourceRetryContext.from_snapshot(resource_retry_context)
            if context.request != request or context.learner != learner:
                raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409)
            snapshot["resource_retry_context"] = context.model_dump(mode="json")
            # Older workers must reject this dispatch instead of silently
            # starting an ordinary diagnose/retrieve/plan workflow.
            snapshot["workflow_version"] = RESOURCE_RETRY_WORKFLOW_VERSION
        return snapshot

    def run_claim(self, claim):
        """Only a persisted, still-owned claim can execute the frozen submission."""
        error_code = None
        resource_ids = []
        learner = None
        try:
            version = claim.snapshot.get("workflow_version")
            if version not in {TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION}:
                raise ValueError("unsupported frozen workflow")
            if (version == RESOURCE_RETRY_WORKFLOW_VERSION) != (claim.snapshot.get("resource_retry_context") is not None):
                raise ValueError("retry dispatch version mismatch")
            req = GenerateRequest.model_validate(claim.request_payload)
            learner = LearnerProfile.model_validate(claim.snapshot["learner"])
            if (req.learner_id != claim.learner_id or learner.learner_id != claim.learner_id
                    or canonical_hash(req.model_dump(mode="json")) != claim.snapshot.get("request_hash")):
                raise ValueError("frozen generation input mismatch")
            with execution_fence(ExecutionFence(claim.run_id, claim.owner, claim.epoch)):
                retry_context = claim.snapshot.get("resource_retry_context")
                response = self.generation_service.generate_with_run_id(
                    learner, req, run_id=claim.run_id, batch_id=claim.batch_id,
                    **({"resource_retry_context": retry_context} if retry_context is not None else {}))
                resource_ids = [item.resource_id for item in response.resources]
                if getattr(response, "workflow_status", None) == "failed":
                    error_code = "GENERATION_EXECUTION_FAILED"
        except ExecutionLeaseLost:
            return False
        except Exception as exc:
            error_code = exc.code.value if isinstance(exc, ApplicationError) else "GENERATION_EXECUTION_FAILED"
            logger.error("Generation attempt failed run_id=%s epoch=%s code=%s type=%s",
                         claim.run_id, claim.epoch, error_code, type(exc).__name__)
        finished = self.job_repo.finish_claim(claim, resource_ids=resource_ids, error_code=error_code)
        if finished and error_code and learner and self.mastery_service:
            self.mastery_service.release_failed_generation(learner, run_id=claim.run_id)
        return finished

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
        metadata = {}
        if hasattr(self.job_repo, "get_dispatch"):
            metadata = self.job_repo.get_dispatch(run_id) or {}
            if metadata.get("dispatch_mode") == "worker":
                raise ExecutionLeaseLost()
        if hasattr(self.job_repo, "try_start_background"):
            if not self.job_repo.try_start_background(run_id):
                return
        else:
            self.job_repo.mark_running(run_id)
        try:
            job = self.job_repo.get(run_id)
            effective_batch_id = batch_id or (job.batch_id if job else run_id)
            snapshot = metadata.get("dispatch_snapshot") or {}
            retry_context = snapshot.get("resource_retry_context")
            if snapshot:
                version = snapshot.get("workflow_version")
                if (version not in {TEXT_WORKFLOW_VERSION, RESOURCE_RETRY_WORKFLOW_VERSION}
                        or (version == RESOURCE_RETRY_WORKFLOW_VERSION) != (retry_context is not None)):
                    raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409)
            if retry_context is not None:
                learner = LearnerProfile.model_validate(snapshot["learner"])
                if canonical_hash(req.model_dump(mode="json")) != snapshot.get("request_hash"):
                    raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=409)
            response = self.generation_service.generate_with_run_id(
                learner,
                req,
                run_id=run_id,
                batch_id=effective_batch_id,
                **({"resource_retry_context": retry_context} if retry_context is not None else {}),
            )
            self.job_repo.mark_completed(
                run_id,
                [resource.resource_id for resource in response.resources],
            )
        except Exception as exc:
            logger.error("Generation job failed run_id=%s type=%s", run_id, type(exc).__name__)
            self.job_repo.mark_failed(run_id, str(exc))
            if self.mastery_service is not None:
                self.mastery_service.release_failed_generation(learner, run_id=run_id)
