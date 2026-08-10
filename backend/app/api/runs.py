from fastapi import APIRouter, Query, Request

from app.config import get_settings
from app.models.persistence import PersistedEvidenceSnapshot, RunSummary, RunTimeline
from app.models.claims import RunClaimsResponse
from app.services.run_query_service import RunQueryService


router = APIRouter()


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
