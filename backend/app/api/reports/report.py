import asyncio
import base64
import json
import re
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.models.reports.contracts import ReportResponse
from app.services.learners.profiles import ProfileService
from app.services.reports.reports import ReportService, ReportSnapshotUnstable

router = APIRouter()


_REVISION_RE = re.compile(r"^rpt_[0-9a-f]{64}$")


def _if_none_match_matches(value: str | None, revision: str) -> bool:
    """Parse the small safe subset we need without treating malformed tags as hits."""
    if not value:
        return False
    for candidate in value.split(","):
        candidate = candidate.strip()
        if candidate.startswith("W/"):
            candidate = candidate[2:].strip()
        if candidate == "*" or candidate == f'"{revision}"':
            return True
    return False


def _profile_and_service(learner_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return profile, container.report_service()


@router.get("/{learner_id}", response_model=ReportResponse)
def get_report(learner_id: str, request: Request, window_days: int = Query(default=30)):
    """获取学情报告"""
    if window_days not in {7, 30, 90}:
        raise HTTPException(status_code=422, detail="window_days 必须为 7、30 或 90")
    profile, report_service = _profile_and_service(learner_id, request)
    try:
        report = report_service.build_report(profile, window_days=window_days)
    except ReportSnapshotUnstable:
        raise HTTPException(status_code=503, detail={"code": "REPORT_SNAPSHOT_UNSTABLE", "message": "报告数据正在更新，请稍后重试"})
    headers = {"ETag": f'"{report["report_revision"]}"', "Cache-Control": "private, no-cache"}
    if _if_none_match_matches(request.headers.get("if-none-match"), report["report_revision"]):
        return Response(status_code=304, headers=headers)
    return JSONResponse(content=ReportResponse.model_validate(report).model_dump(mode="json"), headers=headers)


@router.get("/{learner_id}/resource-credibility")
def get_resource_credibility(learner_id: str, request: Request, limit: int = Query(default=20, ge=1, le=100), cursor: str | None = None):
    profile, report_service = _profile_and_service(learner_id, request)
    items = report_service._resource_credibility(report_service._visible_resources(learner_id))["items"]
    start = 0
    if cursor:
        try:
            decoded = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode("utf-8")
            boundary = json.loads(decoded)
            key = (boundary["published_at"], boundary["resource_id"])
            start = next(index + 1 for index, item in enumerate(items) if ((item["published_at"].isoformat() if item["published_at"] else None), item["resource_id"]) == key)
        except (ValueError, KeyError, StopIteration, json.JSONDecodeError, UnicodeDecodeError):
            raise HTTPException(status_code=400, detail={"code": "REPORT_CURSOR_INVALID", "message": "报告分页游标无效"})
    page = items[start:start + limit]
    next_cursor = None
    if start + limit < len(items) and page:
        last = page[-1]
        raw = json.dumps({"published_at": last["published_at"].isoformat() if last["published_at"] else None, "resource_id": last["resource_id"]}, separators=(",", ":"))
        next_cursor = base64.urlsafe_b64encode(raw.encode("utf-8")).decode("ascii").rstrip("=")
    return {"items": page, "next_cursor": next_cursor}


@router.get("/{learner_id}/events")
async def stream_report(learner_id: str, request: Request, window_days: int = Query(default=30), after_revision: str | None = None):
    if window_days not in {7, 30, 90}:
        raise HTTPException(status_code=422, detail="window_days 必须为 7、30 或 90")
    profile, report_service = _profile_and_service(learner_id, request)
    cursor = request.headers.get("last-event-id") or after_revision
    if cursor and not _REVISION_RE.fullmatch(cursor):
        raise HTTPException(status_code=400, detail={"code": "REPORT_STREAM_CURSOR_INVALID", "message": "报告流游标无效"})

    async def events():
        previous = None
        previous_parts = None
        last_activity = datetime.now(timezone.utc)
        settings = get_settings()
        while not await request.is_disconnected():
            try:
                current_profile = request.app.container.profile_service().get(learner_id)
                if current_profile is None:
                    return
                snapshot = report_service.build_report(current_profile, window_days=window_days)
                revision = snapshot["report_revision"]
                parts = snapshot["freshness"]["source_revisions"]
                payload = {"schema_version": "1.0", "learner_id": learner_id, "report_revision": revision,
                           "as_of_profile_version": snapshot["as_of_profile_version"], "data_as_of": snapshot["data_as_of"],
                           "window_days": window_days}
                if previous is None:
                    payload["replay_mode"] = "current_snapshot"
                    yield f"id: {revision}\nevent: report_snapshot\ndata: {json.dumps(payload, default=str)}\n\n"
                    last_activity = datetime.now(timezone.utc)
                elif revision != previous:
                    payload["changed_domains"] = sorted(key for key in parts if parts.get(key) != previous_parts.get(key))
                    yield f"id: {revision}\nevent: report_changed\ndata: {json.dumps(payload, default=str)}\n\n"
                    last_activity = datetime.now(timezone.utc)
                elif (datetime.now(timezone.utc) - last_activity).total_seconds() >= settings.report_sse_heartbeat_seconds:
                    ping = {"learner_id": learner_id, "report_revision": revision, "server_time": datetime.now(timezone.utc)}
                    yield f"event: ping\ndata: {json.dumps(ping, default=str)}\n\n"
                    last_activity = datetime.now(timezone.utc)
                previous, previous_parts = revision, parts
            except Exception:
                safe = {"code": "REPORT_STREAM_UNAVAILABLE", "safe_message": "报告自动更新暂时不可用", "report_revision": previous}
                yield f"event: stream_error\ndata: {json.dumps(safe)}\n\n"
                return
            await asyncio.sleep(settings.report_sse_poll_interval_seconds)

    return StreamingResponse(events(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
