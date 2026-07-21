from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import LearnerProfile, ProfileStatusResponse
from app.services.learner_service import LearnerService

router = APIRouter()


@router.post("/profile", response_model=ProfileStatusResponse, status_code=200)
def create_or_update_profile(profile: LearnerProfile, request: Request):
    """创建或更新学习者画像"""
    container = request.app.container
    service: LearnerService = container.learner_service()
    service.create_or_update(profile)
    return {"status": "success", "learner_id": profile.learner_id}


@router.get("/profile/{learner_id}", response_model=LearnerProfile)
def get_profile(learner_id: str, request: Request):
    """获取学习者画像"""
    container = request.app.container
    service: LearnerService = container.learner_service()
    profile = service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者不存在")
    return profile
