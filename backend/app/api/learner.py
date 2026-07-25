from fastapi import APIRouter, HTTPException, Query, Request

from app.models.schemas import LearnerProfile, LearnerProfileUpdate, ProfileStatusResponse, StatusResponse
from app.services.learner_service import LearnerService

router = APIRouter()


@router.post("/profile", response_model=ProfileStatusResponse, status_code=200)
def create_or_update_profile(profile: LearnerProfile, request: Request):
    """创建或更新学习者画像"""
    container = request.app.container
    service: LearnerService = container.learner_service()
    service.create_or_update(profile)
    return {"status": "success", "learner_id": profile.learner_id}


@router.get("/list")
def list_profiles(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    skill_level: str | None = None,
):
    """分页查询学习者画像，可按能力等级过滤。"""
    service: LearnerService = request.app.container.learner_service()
    return service.list_with_pagination(page, page_size, skill_level)


@router.get("/profile/{learner_id}", response_model=LearnerProfile)
def get_profile(learner_id: str, request: Request):
    """获取学习者画像"""
    container = request.app.container
    service: LearnerService = container.learner_service()
    profile = service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者不存在")
    return profile


@router.patch("/profile/{learner_id}")
def update_profile(learner_id: str, payload: LearnerProfileUpdate, request: Request):
    """白名单部分更新学习者画像，不允许修改 learner_id。"""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="至少提供一个待更新字段")
    service: LearnerService = request.app.container.learner_service()
    profile = service.update_partial(learner_id, updates)
    if profile is None:
        raise HTTPException(status_code=404, detail="学习者不存在")
    return {"status": "success", "learner_id": learner_id, "updated_fields": sorted(updates)}


@router.delete("/profile/{learner_id}", response_model=StatusResponse)
def delete_profile(learner_id: str, request: Request):
    """删除学习者画像及其诊断依赖记录，保留匿名化 Agent 审计轨迹。"""
    service: LearnerService = request.app.container.learner_service()
    if not service.delete(learner_id):
        raise HTTPException(status_code=404, detail="学习者不存在")
    return {"status": "success", "message": "学习者画像已删除"}
