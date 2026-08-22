"""HTTP endpoints for the isolated interactive-courseware workflow."""

import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import Response, StreamingResponse

from app.api.dependencies import ensure_profile_access
from app.core.courseware.security import security_policy
from app.models.courseware import (
    CoursewareJobCreateRequest, CoursewareJobDetail, CoursewareJobResponse, CoursewareResourceDetail,
)


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
def create_courseware_job(payload: CoursewareJobCreateRequest, request: Request, background_tasks: BackgroundTasks):
    profile = request.app.container.profile_service().get(payload.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    job = _service(request).create_job(payload)
    if job.status == "queued":
        background_tasks.add_task(_service(request).run_job, job.run_id)
    return job


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
    terminal = {"approved_pending_publish", "published", "published_with_warnings", "rejected_admission", "failed"}

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
def retry_courseware_job(run_id: str, request: Request, background_tasks: BackgroundTasks):
    job = _authorized_job(run_id, request)
    if job.status in {"published", "published_with_warnings"}:
        return job
    background_tasks.add_task(_service(request).retry, run_id)
    return _service(request).get_job(run_id) or job


@router.post("/courseware/jobs/{run_id}/scenes/{scene_id}/retry", response_model=CoursewareJobResponse)
def retry_courseware_scene(run_id: str, scene_id: str, request: Request, background_tasks: BackgroundTasks):
    job = _authorized_job(run_id, request)
    detail = _service(request).get_job_detail(run_id)
    if detail is None or all(scene.scene_id != scene_id for scene in detail.scenes):
        raise HTTPException(status_code=404, detail="课件场景不存在")
    if job.status not in {"approved_pending_publish", "published", "published_with_warnings"}:
        background_tasks.add_task(_service(request).retry_scene, run_id, scene_id)
    return _service(request).get_job(run_id) or job


@router.post("/courseware/jobs/{run_id}/publish", response_model=CoursewareJobResponse)
def publish_courseware_job(run_id: str, request: Request):
    job = _authorized_job(run_id, request)
    if job.status != "approved_pending_publish":
        return job
    return _service(request).publish(run_id) or job


@router.get("/courseware/items/{resource_id}", response_model=CoursewareResourceDetail)
def get_courseware_resource(resource_id: str, request: Request):
    return _authorized_resource(resource_id, request)


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
            "Content-Security-Policy": security_policy(include_frame_ancestors=True),
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
