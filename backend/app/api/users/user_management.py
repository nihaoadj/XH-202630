from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import request_user
from app.models.users.users import UserProfile, UserProfileCreate, UserProfileUpdate
from app.services.users.users import UserService

router = APIRouter()


@router.get("/")
def list_users(request: Request):
    current_user = request_user(request)
    if current_user is not None:
        return {"items": [current_user]}
    service: UserService = request.app.container.user_service()
    return {"items": service.list_all()}


@router.get("/{user_id}", response_model=UserProfile)
def get_user(user_id: str, request: Request):
    current_user = request_user(request)
    if current_user is not None and current_user.user_id != user_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    service: UserService = request.app.container.user_service()
    profile = service.get(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@router.post("/", response_model=UserProfile)
def create_user(payload: UserProfileCreate, request: Request):
    if request_user(request) is not None:
        raise HTTPException(status_code=403, detail="请通过注册功能创建用户")
    service: UserService = request.app.container.user_service()
    return service.create(payload.model_dump())


@router.patch("/{user_id}", response_model=UserProfile)
def update_user(user_id: str, payload: UserProfileUpdate, request: Request):
    current_user = request_user(request)
    if current_user is not None and current_user.user_id != user_id:
        raise HTTPException(status_code=404, detail="用户不存在")
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="至少提供一个待更新字段")
    service: UserService = request.app.container.user_service()
    updated = service.update_partial(user_id, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return updated
