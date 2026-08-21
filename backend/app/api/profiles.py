from fastapi import APIRouter, HTTPException, Query, Request

from app.api.dependencies import ensure_profile_access, request_user
from app.models.schemas import LearnerProfile, LearnerProfileUpdate, StatusResponse
from app.services.profile_service import ProfileService

router = APIRouter()


@router.get("/")
def list_profiles(
    request: Request,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    skill_level: str | None = None,
):
    """分页查询由问卷或诊断流程产生的学习者画像。"""
    service: ProfileService = request.app.container.profile_service()
    current_user = request_user(request)
    return service.list_with_pagination(
        page,
        page_size,
        skill_level,
        user_id=current_user.user_id if current_user else None,
    )


@router.get("/{learner_id}", response_model=LearnerProfile)
def get_profile(learner_id: str, request: Request):
    """查询学习者画像。"""
    service: ProfileService = request.app.container.profile_service()
    profile = ensure_profile_access(request, service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在，请先完成入门问卷")
    return profile


@router.patch("/{learner_id}")
def update_profile(learner_id: str, payload: LearnerProfileUpdate, request: Request):
    """白名单部分更新问卷画像，不允许修改 learner_id。"""
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="至少提供一个待更新字段")
    service: ProfileService = request.app.container.profile_service()
    if ensure_profile_access(request, service.get(learner_id)) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在，请先完成入门问卷")
    profile = service.update_partial(learner_id, updates)
    if profile is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在，请先完成入门问卷")
    return {"status": "success", "learner_id": learner_id, "updated_fields": sorted(updates)}


@router.delete("/{learner_id}", response_model=StatusResponse)
def delete_profile(learner_id: str, request: Request):
    """永久删除学习者画像及其全部学习、资源、审核与运行记录。"""
    service: ProfileService = request.app.container.profile_service()
    if ensure_profile_access(request, service.get(learner_id)) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    if not service.delete(learner_id):
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return {"status": "success", "message": "学习者画像及其相关内容已永久删除"}
