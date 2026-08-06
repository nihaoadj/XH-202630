from fastapi import APIRouter, HTTPException, Request

from app.models.user_schemas import UserProfile, UserProfileCreate, UserProfileUpdate
from app.services.user_service import UserService

router = APIRouter()


@router.get("/")
def list_users(request: Request):
    service: UserService = request.app.container.user_service()
    return {"items": service.list_all()}


@router.get("/{user_id}", response_model=UserProfile)
def get_user(user_id: str, request: Request):
    service: UserService = request.app.container.user_service()
    profile = service.get(user_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return profile


@router.post("/", response_model=UserProfile)
def create_user(payload: UserProfileCreate, request: Request):
    service: UserService = request.app.container.user_service()
    return service.create(payload.model_dump())


@router.patch("/{user_id}", response_model=UserProfile)
def update_user(user_id: str, payload: UserProfileUpdate, request: Request):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="至少提供一个待更新字段")
    service: UserService = request.app.container.user_service()
    updated = service.update_partial(user_id, updates)
    if updated is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    return updated
