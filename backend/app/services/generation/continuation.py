"""Create a continuation while retaining the original persistence order."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.db.feedback.feedback_loop_base import BaseFeedbackLoopRepository
from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
    GenerateRequest,
    GenerationJobCreateResponse,
    LearnerProfile,
    LearningResource,
)
from app.services.learning_documents.resources import ResourceService

if TYPE_CHECKING:
    from app.services.generation.jobs import GenerationJobService


class BatchContinuationError(ValueError):
    """A continuation input failed an existing use-case check."""

    def __init__(self, *, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _resource_context(resources: list[LearningResource]) -> list[dict[str, Any]]:
    """Keep the continuation prompt bounded while retaining batch context."""
    summaries = []
    for resource in resources[-12:]:
        content = " ".join((resource.content_text or "").split())
        summaries.append(
            {
                "resource_type": resource.resource_type,
                "difficulty": resource.difficulty,
                "knowledge_points": resource.knowledge_points[:8],
                "content_summary": content[:600],
            }
        )
    return summaries


@dataclass(frozen=True)
class PreparedContinuation:
    generation_request: GenerateRequest
    batch_id: str
    payload: ContinueResourceBatchRequest
    source_job_run_id: str
    source_run_id: str | None
    feedback_attempt_id: str | None
    feedback_decision_id: str | None
    relation_type: str

    @property
    def feedback_repo_call_count(self) -> int:
        if not self.feedback_attempt_id or not self.feedback_decision_id:
            return 0
        return 2 if self.relation_type == "retry" and self.source_run_id else 1


def prepare_continuation(
    generation_job_service: GenerationJobService,
    learner: LearnerProfile,
    batch_id: str,
    payload: ContinueResourceBatchRequest,
    *,
    resource_service_factory: Callable[[], ResourceService],
):
    """Perform the original read/validation phase without mutating repositories."""
    batch_jobs = [
        item
        for item in generation_job_service.list_jobs(learner.learner_id).items
        if (item.batch_id or item.run_id) == batch_id
    ]
    source_job = (
        next(
            (item for item in batch_jobs if item.run_id == payload.source_run_id),
            None,
        )
        if payload.source_run_id
        else next(iter(batch_jobs), None)
    )
    if source_job is None:
        detail = (
            "指定的源任务不属于该资源批次"
            if payload.source_run_id
            else "资源批次不存在"
        )
        raise BatchContinuationError(status_code=404, detail=detail)

    try:
        source_request = GenerateRequest.model_validate(source_job.request_payload)
    except ValueError as exc:
        raise BatchContinuationError(
            status_code=409, detail="资源批次的原始生成参数不可用"
        ) from exc

    resource_service: ResourceService = resource_service_factory()
    batch_resources = [
        item
        for item in resource_service.list_by_learner(learner.learner_id)
        if (item.batch_id or item.run_id) == batch_id
    ]
    constraints = dict(source_request.constraints)
    constraints["continuation_context"] = _resource_context(batch_resources)
    if payload.instructions and payload.instructions.strip():
        constraints["continuation_instructions"] = payload.instructions.strip()
    if payload.replace_existing_types:
        # Keep prior artifacts auditable, while allowing the learner-facing
        # batch projection to use this run as the latest version of each type.
        constraints["replacement_resource_types"] = list(payload.resource_types)
    request_updates = {
        "resource_types": payload.resource_types,
        "constraints": constraints,
    }
    if payload.include_claim_check is not None:
        request_updates["include_claim_check"] = payload.include_claim_check
    try:
        # Revalidate the copied request so an explicit Claim option cannot
        # bypass the invariant that Claim review requires normal review.
        generation_request = GenerateRequest.model_validate(
            {**source_request.model_dump(mode="python"), **request_updates}
        )
    except ValueError as exc:
        raise BatchContinuationError(status_code=422, detail=str(exc)) from exc

    feedback_attempt_id = constraints.get("feedback_attempt_id")
    feedback_decision_id = constraints.get("feedback_decision_id")
    relation_type = (
        "retry"
        if payload.replace_existing_types and "重新生成" in (payload.instructions or "")
        else "continuation"
    )
    return PreparedContinuation(
        generation_request=generation_request,
        batch_id=batch_id,
        payload=payload,
        source_job_run_id=source_job.run_id,
        source_run_id=payload.source_run_id,
        feedback_attempt_id=str(feedback_attempt_id) if feedback_attempt_id else None,
        feedback_decision_id=str(feedback_decision_id)
        if feedback_decision_id
        else None,
        relation_type=relation_type,
    )


def execute_continuation(
    prepared: PreparedContinuation,
    generation_job_service: GenerationJobService,
    learner: LearnerProfile,
    *,
    feedback_repo_factory: Callable[[], BaseFeedbackLoopRepository],
    run_id: str | None = None,
) -> tuple[GenerationJobCreateResponse, GenerateRequest]:
    """Create the job, attach feedback lineage, then supersede its source.

    The repository providers are resolved only when their original use is
    reached; transaction callers may supply a prevalidated call-local factory.
    """
    create_kwargs = {"batch_id": prepared.batch_id}
    if run_id is not None:
        create_kwargs["run_id"] = run_id
    job = generation_job_service.create_job(
        learner,
        prepared.generation_request,
        **create_kwargs,
    )
    if prepared.feedback_attempt_id and prepared.feedback_decision_id:
        source_relation_id = None
        if prepared.relation_type == "retry" and prepared.source_run_id:
            source_relation = feedback_repo_factory().get_followup_relation(
                prepared.source_run_id
            )
            source_relation_id = (
                source_relation.get("relation_id") if source_relation else None
            )
        feedback_repo_factory().attach_followup(
            attempt_id=prepared.feedback_attempt_id,
            decision_id=prepared.feedback_decision_id,
            parent_run_id=prepared.source_run_id or prepared.source_job_run_id,
            child_run_id=job.run_id,
            trigger_type="resource_append",
            status="queued",
            relation_type=prepared.relation_type,
            source_relation_id=source_relation_id,
            source_child_run_id=prepared.source_run_id
            if prepared.relation_type == "retry"
            else None,
        )
    if prepared.source_run_id and prepared.payload.replace_source_run:
        generation_job_service.mark_superseded(prepared.source_run_id, job.run_id)
    return job, prepared.generation_request


def create_continuation(
    generation_job_service: GenerationJobService,
    learner: LearnerProfile,
    batch_id: str,
    payload: ContinueResourceBatchRequest,
    *,
    resource_service_factory: Callable[[], ResourceService],
    feedback_repo_factory: Callable[[], BaseFeedbackLoopRepository],
) -> tuple[GenerationJobCreateResponse, GenerateRequest]:
    """Preserve the direct use-case entry point for older callers and stubs."""
    prepared = prepare_continuation(
        generation_job_service,
        learner,
        batch_id,
        payload,
        resource_service_factory=resource_service_factory,
    )
    return execute_continuation(
        prepared,
        generation_job_service,
        learner,
        feedback_repo_factory=feedback_repo_factory,
    )
