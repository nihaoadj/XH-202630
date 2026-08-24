"""HTTP endpoints for the isolated interactive-courseware workflow."""

import asyncio
import json

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import ensure_profile_access
from app.core.courseware.security import security_policy_for_artifact
from app.models.courseware import (
    CoursewareBatchCreateRequest, CoursewareBatchJobResponse, CoursewareJobCreateRequest, CoursewareJobDetail, CoursewareJobListResponse, CoursewareJobResponse, CoursewareResourceDetail,
)
from app.models.courseware.events import CoursewareLearningEventBatch


router = APIRouter()


def _service(request: Request):
    return request.app.container.courseware_service()


def _authorized_job(run_id: str, request: Request):
    job = _service(request).get_job(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="课件任务不存在")
    profile = request.app.container.profile_service().get(job.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="课件任务不存在")
    return job


def _authorized_resource(resource_id: str, request: Request) -> CoursewareResourceDetail:
    resource = _service(request).get_resource(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="课件资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="课件资源不存在")
    return resource


@router.post("/courseware/jobs", response_model=CoursewareJobResponse)
def create_courseware_job(payload: CoursewareJobCreateRequest, request: Request):
    profile = request.app.container.profile_service().get(payload.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    job = _service(request).create_job(payload)
    return job


@router.post("/courseware/jobs/batch", response_model=CoursewareBatchJobResponse, status_code=202)
def create_courseware_jobs(payload: CoursewareBatchCreateRequest, request: Request):
    profile = request.app.container.profile_service().get(payload.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return _service(request).create_jobs_for_resources(payload)


@router.get("/courseware/jobs", response_model=CoursewareJobListResponse)
def list_courseware_jobs(learner_id: str, request: Request):
    profile = request.app.container.profile_service().get(learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return {"items": _service(request).list_jobs(learner_id)}


@router.get("/courseware/jobs/{run_id}", response_model=CoursewareJobResponse)
def get_courseware_job(run_id: str, request: Request):
    return _authorized_job(run_id, request)


@router.get("/courseware/jobs/{run_id}/detail", response_model=CoursewareJobDetail)
def get_courseware_job_detail(run_id: str, request: Request):
    _authorized_job(run_id, request)
    return _service(request).get_job_detail(run_id)


@router.get("/courseware/jobs/{run_id}/events")
def stream_courseware_events(run_id: str, request: Request, after_sequence: int = 0):
    _authorized_job(run_id, request)
    terminal = {
        "approved_pending_publish", "published", "published_with_warnings",
        "rejected_admission", "failed", "quarantined", "release_blocked",
        "cancelled", "timed_out",
    }

    async def stream():
        sequence = max(0, after_sequence)
        idle_ticks = 0
        while True:
            if await request.is_disconnected():
                return
            events = _service(request).events(run_id, sequence)
            for event in events:
                sequence = event["event_sequence"]
                payload = json.dumps(event, ensure_ascii=False, default=str, separators=(",", ":"))
                yield f"id: {sequence}\nevent: courseware_progress\ndata: {payload}\n\n"
            job = _service(request).get_job(run_id)
            if job is None or (job.status in terminal and not events):
                return
            idle_ticks += 1
            if idle_ticks % 40 == 0:
                yield ": keep-alive\n\n"
            await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store"})


@router.post("/courseware/jobs/{run_id}/retry", response_model=CoursewareJobResponse)
def retry_courseware_job(run_id: str, request: Request):
    job = _authorized_job(run_id, request)
    if job.status in {"published", "published_with_warnings"}:
        return job
    return _service(request).retry(run_id) or job


@router.post("/courseware/jobs/{run_id}/cancel", response_model=CoursewareJobResponse)
def cancel_courseware_job(run_id: str, request: Request):
    job = _authorized_job(run_id, request)
    return _service(request).cancel(run_id) or job


@router.post("/courseware/jobs/{run_id}/scenes/{scene_id}/retry", response_model=CoursewareJobResponse)
def retry_courseware_scene(run_id: str, scene_id: str, request: Request):
    job = _authorized_job(run_id, request)
    detail = _service(request).get_job_detail(run_id)
    if detail is None or all(scene.scene_id != scene_id for scene in detail.scenes):
        raise HTTPException(status_code=404, detail="课件场景不存在")
    # Scene retry is intentionally available after publication: it creates a
    # new scene revision without replaying the whole course workflow.
    _service(request).retry_scene(run_id, scene_id, enqueue_only=True)
    return _service(request).get_job(run_id) or job


@router.get("/courseware/jobs/{run_id}/scenes/{scene_id}/review")
def get_courseware_scene_review(run_id: str, scene_id: str, request: Request):
    """Return review-safe scene diagnostics without exposing prompts or raw model output."""
    _authorized_job(run_id, request)
    detail = _service(request).get_job_detail(run_id)
    if detail is None or all(scene.scene_id != scene_id for scene in detail.scenes):
        raise HTTPException(status_code=404, detail="课件场景不存在")
    service = _service(request)
    spec = service.repo.get_spec_by_run(run_id)
    stored = service.repo.get_scene(scene_id)
    if spec is None or stored is None:
        raise HTTPException(status_code=404, detail="课件场景不存在")
    return {
        "scene_id": scene_id,
        "scene": stored["scene_json"],
        "status": stored["status"],
        "attempt": stored["attempt"],
        "input_snapshot_hash": stored.get("input_snapshot_hash"),
        "agent_version": stored.get("agent_version"),
        "prompt_version": stored.get("prompt_version"),
        "reviews": [review for review in detail.reviews if review.get("scene_id") in {None, scene_id}],
        "revisions": service.repo.list_scene_revisions(scene_id),
    }


@router.post("/courseware/jobs/{run_id}/publish", response_model=CoursewareJobResponse)
def publish_courseware_job(run_id: str, request: Request):
    job = _authorized_job(run_id, request)
    if job.status != "approved_pending_publish":
        return job
    return _service(request).publish(run_id) or job


@router.get("/courseware/items/{resource_id}", response_model=CoursewareResourceDetail)
def get_courseware_resource(resource_id: str, request: Request):
    return _authorized_resource(resource_id, request)


@router.post("/courseware/items/{resource_id}/learning-events")
def ingest_courseware_learning_events(resource_id: str, payload: CoursewareLearningEventBatch, request: Request):
    resource = _authorized_resource(resource_id, request)
    current_release = resource.released_release_id
    if not current_release:
        raise HTTPException(status_code=409, detail={"code": "COURSEWARE_RELEASE_UNAVAILABLE", "message": "课件当前没有可学习 release"})
    events = [item.model_dump(mode="json") for item in payload.events]
    if any(item.get("resource_id") != resource_id for item in events):
        raise HTTPException(status_code=400, detail="事件资源与当前课件不匹配")
    if any(item.get("release_id") != current_release for item in events):
        raise HTTPException(status_code=409, detail={"code": "COURSEWARE_RELEASE_NOT_CURRENT", "message": "学习事件必须写入当前 release"})
    acknowledged = _service(request).ingest_learning_events(events)
    return {"acknowledged_event_ids": [item["event_id"] for item in acknowledged]}


@router.get("/courseware/items/{resource_id}/learning-progress")
def get_courseware_learning_progress(resource_id: str, release_id: str, request: Request):
    resource = _authorized_resource(resource_id, request)
    if not resource.released_release_id:
        raise HTTPException(status_code=409, detail={"code": "COURSEWARE_RELEASE_UNAVAILABLE", "message": "课件当前没有可学习 release"})
    if release_id != resource.released_release_id:
        raise HTTPException(status_code=409, detail={"code": "COURSEWARE_RELEASE_NOT_CURRENT", "message": "只能读取当前 release 的学习进度"})
    return _service(request).learning_progress(resource_id, release_id)


@router.get("/courseware/items/{resource_id}/preview")
def preview_courseware_resource(resource_id: str, request: Request):
    _authorized_resource(resource_id, request)
    artifact = _service(request).artifact(resource_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="课件文件不存在")
    _, content = artifact
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Security-Policy": security_policy_for_artifact(
                content,
                include_frame_ancestors=True,
            ),
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/courseware/items/{resource_id}/file")
def download_courseware_resource(resource_id: str, request: Request):
    _authorized_resource(resource_id, request)
    artifact = _service(request).artifact(resource_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="课件文件不存在")
    _, content = artifact
    return Response(
        content=content,
        media_type="text/html; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{resource_id}.html"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.get("/courseware/items/{resource_id}/packages/{package_format}")
def download_courseware_package(resource_id: str, package_format: str, request: Request):
    _authorized_resource(resource_id, request)
    if package_format not in {"zip", "scorm", "xapi"}:
        raise HTTPException(status_code=400, detail="仅支持 zip、scorm 或 xapi 格式")
    artifact = _service(request).packaged_artifact(resource_id, package_format)
    if artifact is None:
        raise HTTPException(status_code=404, detail="课件导出包不存在")
    _, content = artifact
    return Response(
        content=content, media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{resource_id}.{package_format}.zip"',
            "X-Content-Type-Options": "nosniff", "Cache-Control": "private, no-store",
        },
    )
