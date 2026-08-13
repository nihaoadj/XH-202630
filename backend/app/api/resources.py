from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response

from app.api.dependencies import ensure_profile_access
from app.core.file_storage import load_resource_file
from app.models.schemas import ResourceListResponse
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService

router = APIRouter()


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


@router.get("/{learner_id}", response_model=ResourceListResponse)
def list_resources(
    learner_id: str,
    request: Request,
    resource_type: str | None = None,
    difficulty: str | None = None,
    run_id: str | None = None,
):
    """查询学习者生成资源历史"""
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    resource_service: ResourceService = container.resource_service()
    resources = resource_service.list_by_learner_with_filter(learner_id, resource_type, difficulty, run_id)
    return {
        "learner_id": learner_id,
        "total": len(resources),
        "resources": resources,
    }
