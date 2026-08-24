from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
from fastapi.responses import Response

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.core.storage.file_storage import load_resource_file
from app.core.health import build_health_report
from app.models.learning_documents.schemas import (
    ContinueResourceBatchRequest,
    GenerateRequest,
    GenerationJobCreateResponse,
    ResourceListResponse,
    ResourceDetailResponse,
)
from app.services.generation.jobs import GenerationJobService
from app.services.learners.profiles import ProfileService
from app.services.learning_documents.resources import ResourceService

router = APIRouter()


def _resource_context(resources: list) -> list[dict]:
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


@router.post("/batches/{batch_id}/continuations", response_model=GenerationJobCreateResponse)
def continue_resource_batch(
    batch_id: str,
    payload: ContinueResourceBatchRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Create a new auditable Run in an existing batch.

    A full-batch retry supersedes its source run. A single-resource retry only
    replaces that resource's visible version inside the batch.
    """
    report = build_health_report(get_settings())
    if report.status == "not_ready":
        detail = "生成依赖未就绪"
        if report.error_codes:
            detail = f"{detail}：{', '.join(report.error_codes)}"
        raise HTTPException(status_code=503, detail=detail)

    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    learner = ensure_profile_access(request, profile_service.get(payload.learner_id))
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_job_service: GenerationJobService = container.generation_job_service()
    batch_jobs = [
        item
        for item in generation_job_service.list_jobs(learner.learner_id).items
        if (item.batch_id or item.run_id) == batch_id
    ]
    source_job = next(
        (item for item in batch_jobs if item.run_id == payload.source_run_id),
        None,
    ) if payload.source_run_id else next(iter(batch_jobs), None)
    if source_job is None:
        detail = "指定的源任务不属于该资源批次" if payload.source_run_id else "资源批次不存在"
        raise HTTPException(status_code=404, detail=detail)

    try:
        source_request = GenerateRequest.model_validate(source_job.request_payload)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail="资源批次的原始生成参数不可用") from exc

    resource_service: ResourceService = container.resource_service()
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
    generation_request = source_request.model_copy(
        update={"resource_types": payload.resource_types, "constraints": constraints}
    )
    job = generation_job_service.create_job(
        learner,
        generation_request,
        batch_id=batch_id,
    )
    if payload.source_run_id and payload.replace_source_run:
        generation_job_service.mark_superseded(payload.source_run_id, job.run_id)
    background_tasks.add_task(
        generation_job_service.run_job,
        learner,
        generation_request,
        job.run_id,
        job.batch_id,
    )
    return job


@router.get("/file/{resource_id}")
def download_resource(resource_id: str, request: Request):
    """通过资源 ID 下载受控目录中的生成文件，拒绝任意路径访问。"""
    resource_service: ResourceService = request.app.container.resource_service()
    resource = resource_service.get(resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id or "")
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    if resource.publication_status != "published":
        raise HTTPException(status_code=404, detail="资源不存在")
    if not resource.file_path:
        raise HTTPException(status_code=404, detail="该资源没有可下载文件")
    try:
        content = load_resource_file(resource.file_path)
    except (OSError, ValueError):
        raise HTTPException(status_code=404, detail="资源文件不存在或路径不安全") from None
    filename = Path(resource.file_path).name
    return Response(
        content=content,
        media_type=resource.mime_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _authorized_published_resource(resource_id: str, request: Request):
    service: ResourceService = request.app.container.resource_service()
    resource = service.get(resource_id)
    if resource is None or resource.publication_status != "published":
        raise HTTPException(status_code=404, detail="资源不存在")
    profile = request.app.container.profile_service().get(resource.learner_id or "")
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return resource


@router.get("/items/{resource_id}", response_model=ResourceDetailResponse)
def get_resource_detail(resource_id: str, request: Request):
    _authorized_published_resource(resource_id, request)
    service: ResourceService = request.app.container.resource_service()
    detail = service.get_published_detail(resource_id)
    if detail is None:
        raise HTTPException(status_code=404, detail="资源不存在")
    return {"resource": detail}


@router.get("/{learner_id}", response_model=ResourceListResponse)
def list_resources(
    learner_id: str,
    request: Request,
    resource_type: str | None = None,
    difficulty: str | None = None,
    run_id: str | None = None,
    batch_id: str | None = None,
    page: int | None = Query(default=None, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    summary_only: bool = False,
):
    """查询学习者生成资源历史"""
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    resource_service: ResourceService = container.resource_service()
    if page is None:
        resources = resource_service.list_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id)
        total = len(resources)
    else:
        resources, total = resource_service.list_page_by_learner_with_filter(
            learner_id, resource_type, difficulty, run_id, batch_id,
            page=page, page_size=page_size)
    if summary_only:
        resources = [item.model_copy(update={"content_text": None, "file_path": None})
                     for item in resources]
    return {
        "learner_id": learner_id,
        "total": total,
        "resources": resources,
        "page": page,
        "page_size": page_size if page is not None else None,
        "has_next": bool(page is not None and page * page_size < total),
        "summary_only": summary_only,
    }
