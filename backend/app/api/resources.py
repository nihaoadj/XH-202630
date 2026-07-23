from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import ResourceListResponse
from app.services.learner_service import LearnerService
from app.services.resource_service import ResourceService

router = APIRouter()


@router.get("/{learner_id}", response_model=ResourceListResponse)
def list_resources(learner_id: str, request: Request):
    """查询学习者生成资源历史"""
    container = request.app.container

    learner_service: LearnerService = container.learner_service()
    profile = learner_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    resource_service: ResourceService = container.resource_service()
    resources = resource_service.list_by_learner(learner_id)
    return {
        "learner_id": learner_id,
        "total": len(resources),
        "resources": resources,
    }
