from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import ReviewSummary
from app.services.review_service import ReviewService

router = APIRouter()


@router.get("/{resource_id}", response_model=ReviewSummary)
def get_resource_review(resource_id: str, request: Request):
    """查询资源的最近一次审核摘要、Claim 与证据引用。"""
    service: ReviewService = request.app.container.review_service()
    review = service.get_by_resource(resource_id)
    if review is None:
        raise HTTPException(status_code=404, detail="资源审核记录不存在")
    return review
