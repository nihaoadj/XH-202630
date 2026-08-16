from fastapi import APIRouter, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.models.persistence import PersistedEvidenceSnapshot, RunSummary, RunTimeline
from app.models.claims import RunClaimsResponse
from app.services.run_query_service import RunQueryService
from app.services.run_event_stream_service import RunEventStreamService


router = APIRouter()


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
