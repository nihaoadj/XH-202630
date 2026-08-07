from fastapi import HTTPException, Request, status

from app.config import get_settings
from app.models.schemas import LearnerProfile
from app.models.user_schemas import UserProfile


def get_current_user(request: Request) -> UserProfile:
    settings = get_settings()
    token = request.cookies.get(settings.auth_cookie_name)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
    user = request.app.container.auth_service().resolve_token(token)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录状态已失效，请重新登录")
    request.state.current_user = user
    return user


def request_user(request: Request) -> UserProfile | None:
    return getattr(request.state, "current_user", None)


def ensure_profile_access(request: Request, profile: LearnerProfile | None) -> LearnerProfile | None:
    current_user = request_user(request)
    if current_user is not None and (profile is None or profile.user_id != current_user.user_id):
        return None
    return profile
