from enum import Enum

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.models.shared.llm_accounting import TaskLLMAccountingResponseV1
from app.models.shared.persistence import PersistedEvidenceSnapshot, RunSummary, RunTimeline
from app.models.reviews.claim_evidence_retrieval import ClaimEvidenceRetrievalSummaryV1
from app.models.reviews.claims import RunClaimsResponse
from app.models.reviews.quality_metrics import RunResourceQualityResponseV1
from app.services.reviews.claim_evidence_retrieval_query import (
    ClaimEvidenceRetrievalNotFound,
)
from app.services.reviews.quality_query import ResourceQualityNotFound
from app.services.runs.llm_accounting import LLMAccountingQueryService
from app.services.runs.queries import RunQueryService
from app.services.runs.events import RunEventStreamService


router = APIRouter()

_TEXT_RUN_TERMINAL_STATUSES = {"completed", "degraded", "human_review", "failed", "interrupted"}


class TextAccountingStage(str, Enum):
    """Controlled stage filter for the text-generation accounting endpoint."""

    diagnose = "diagnose"
    plan = "plan"
    generate = "generate"
    review = "review"
    claim_extract = "claim_extract"
    claim_judge = "claim_judge"


@router.get("/{run_id}/events")
async def stream_run_events(
    run_id: str,
    request: Request,
    after_sequence: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    """Replay and live-tail committed events; transport disconnect is read-only."""

    service: RunEventStreamService = request.app.container.run_event_stream_service()
    cursor = service.resolve_cursor(last_event_id, after_sequence)
    snapshot = await service.prepare(run_id, cursor)
    return StreamingResponse(
        service.stream(
            run_id,
            cursor=cursor,
            initial_snapshot=snapshot,
            is_disconnected=request.is_disconnected,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{run_id}", response_model=RunSummary)
def get_run(run_id: str, request: Request):
    service: RunQueryService = request.app.container.run_query_service()
    return service.get_summary(run_id)


@router.get("/{run_id}/timeline", response_model=RunTimeline)
def get_run_timeline(
    run_id: str,
    request: Request,
    after_sequence: int = Query(default=0, ge=0),
    limit: int | None = Query(default=None, ge=1, le=500),
):
    settings = get_settings()
    effective_limit = limit or settings.workflow_timeline_default_limit
    effective_limit = min(effective_limit, settings.workflow_timeline_max_limit)
    service: RunQueryService = request.app.container.run_query_service()
    return service.get_timeline(
        run_id,
        after_sequence=after_sequence,
        limit=effective_limit,
    )


@router.get("/{run_id}/evidence", response_model=list[PersistedEvidenceSnapshot])
def get_run_evidence(run_id: str, request: Request):
    service: RunQueryService = request.app.container.run_query_service()
    return service.get_evidence(run_id)


@router.get("/{run_id}/claims", response_model=RunClaimsResponse)
def get_run_claims(run_id: str, request: Request):
    service: RunQueryService = request.app.container.run_query_service()
    return service.get_claims(run_id)


@router.get(
    "/{run_id}/claim-evidence-retrieval",
    response_model=ClaimEvidenceRetrievalSummaryV1,
)
def get_run_claim_evidence_retrieval(
    run_id: str,
    request: Request,
    resource_id: str | None = Query(default=None, min_length=1, max_length=128),
):
    """Read-only supplement summary; it never starts or retries retrieval."""

    run_service: RunQueryService = request.app.container.run_query_service()
    run = run_service.get_run(run_id)
    learner_id = getattr(run, "learner_id", None)
    profile = (
        request.app.container.profile_service().get(learner_id) if learner_id else None
    )
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="工作流任务不存在")
    service = request.app.container.claim_evidence_retrieval_query_service()
    try:
        return service.get(run_id, resource_id=resource_id)
    except ClaimEvidenceRetrievalNotFound as exc:
        raise HTTPException(status_code=404, detail="工作流任务不存在") from exc


@router.get("/{run_id}/resource-quality", response_model=RunResourceQualityResponseV1)
def get_run_resource_quality(
    run_id: str,
    request: Request,
    resource_id: str | None = Query(default=None, min_length=1, max_length=128),
):
    """Read-only quality projection for one run.

    This is a separate endpoint on purpose: the new DTOs never enter the
    learning-resource read model, the legacy GenerateReport payload or a
    workflow checkpoint/request hash.  Authorization reuses the same
    run → learner → profile visibility path as the accounting endpoint; a
    missing or invisible run is a uniform 404.
    """

    run_service: RunQueryService = request.app.container.run_query_service()
    run = run_service.get_run(run_id)
    learner_id = getattr(run, "learner_id", None)
    profile = (
        request.app.container.profile_service().get(learner_id) if learner_id else None
    )
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="工作流任务不存在")

    service = request.app.container.resource_quality_query_service()
    try:
        response = service.get_run_quality(run_id, resource_id=resource_id)
    except ResourceQualityNotFound as exc:
        raise HTTPException(status_code=404, detail="资源不存在") from exc

    # Ownership can be revoked while the read runs; never leak after that.
    current = (
        request.app.container.profile_service().get(learner_id) if learner_id else None
    )
    if ensure_profile_access(request, current) is None:
        raise HTTPException(status_code=404, detail="工作流任务不存在")
    return response


@router.get("/{run_id}/llm-accounting", response_model=TaskLLMAccountingResponseV1)
def get_run_llm_accounting(
    run_id: str,
    request: Request,
    include_calls: bool = Query(default=False),
    stage: TextAccountingStage | None = Query(default=None),
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
):
    """Read-only full-chain LLM-call accounting for one text generation run.

    The new endpoint adds the profile-visibility check the legacy run
    endpoints do not perform; missing/invisible runs stay a uniform 404.
    """

    run_service: RunQueryService = request.app.container.run_query_service()
    run = run_service.get_run(run_id)
    learner_id = getattr(run, "learner_id", None)
    profile = (
        request.app.container.profile_service().get(learner_id) if learner_id else None
    )
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="工作流任务不存在")

    try:
        timeline = run_service.get_timeline(run_id, limit=500)
        expected_llm_stages = {
            step.node_name for step in timeline.steps if step.llm_call_id
        }
        status = str(getattr(timeline.run.status, "value", timeline.run.status))
    except Exception:
        expected_llm_stages = None
        status = "running"
    accounting_service: LLMAccountingQueryService = (
        request.app.container.llm_accounting_query_service()
    )
    return accounting_service.query_task(
        domain="learning_documents",
        run_id=run_id,
        include_calls=include_calls,
        stage=stage.value if stage is not None else None,
        cursor=cursor,
        limit=limit,
        task_terminal=status in _TEXT_RUN_TERMINAL_STATUSES,
        expected_llm_stages=expected_llm_stages,
    )
