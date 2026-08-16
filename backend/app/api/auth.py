from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from app.api.dependencies import get_current_user
from app.config import get_settings
from app.models.auth_schemas import AuthResponse, LoginRequest, LogoutResponse, RegisterRequest
from app.models.user_schemas import UserProfile
from app.services.auth_service import (
    InactiveUserError,
    InvalidCredentialsError,
    UsernameAlreadyExistsError,
)


router = APIRouter()


def _set_auth_cookie(response: Response, user_id: str, request: Request) -> None:
    settings = get_settings()
    token = request.app.container.auth_service().create_token(user_id)
    max_age = settings.auth_token_expire_minutes * 60
    response.set_cookie(
        key=settings.auth_cookie_name,
        value=token,
        max_age=max_age,
        httponly=True,
        secure=settings.auth_cookie_secure,
        samesite="lax",
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"


@router.post("/register", response_model=AuthResponse, status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, request: Request, response: Response):
    try:
        user = request.app.container.auth_service().register(payload)
    except UsernameAlreadyExistsError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="用户名已存在") from exc
    _set_auth_cookie(response, user.user_id, request)
    return {"user": user}


@router.post("/login", response_model=AuthResponse)
def login(payload: LoginRequest, request: Request, response: Response):
    try:
        user = request.app.container.auth_service().authenticate(payload.username, payload.password)
    except InvalidCredentialsError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误") from exc
    except InactiveUserError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已停用") from exc
    _set_auth_cookie(response, user.user_id, request)
    return {"user": user}


@router.get("/me", response_model=AuthResponse)
def me(current_user: UserProfile = Depends(get_current_user)):
    return {"user": current_user}


@router.post("/logout", response_model=LogoutResponse)
def logout(response: Response):
    settings = get_settings()
    response.delete_cookie(key=settings.auth_cookie_name, path="/")
    response.headers["Cache-Control"] = "no-store"
    return LogoutResponse()
