from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import ensure_profile_access, request_user
from app.models.schemas import ReviewSummary
from app.services.review_service import ReviewService

router = APIRouter()


@router.get("/{resource_id}", response_model=ReviewSummary)
def get_resource_review(resource_id: str, request: Request):
    """查询资源的最近一次审核摘要、Claim 与证据引用。"""
    if request_user(request) is not None:
        resource = request.app.container.resource_service().get(resource_id)
        if resource is None:
            raise HTTPException(status_code=404, detail="资源审核记录不存在")
        profile = request.app.container.profile_service().get(resource.learner_id or "")
        if ensure_profile_access(request, profile) is None:
            raise HTTPException(status_code=404, detail="资源审核记录不存在")
    service: ReviewService = request.app.container.review_service()
    review = service.get_by_resource(resource_id)
    if review is None:
        raise HTTPException(status_code=404, detail="资源审核记录不存在")
    return review
