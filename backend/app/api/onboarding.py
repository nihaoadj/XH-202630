"""RAG 入门问卷与初始画像接口。"""
from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import InitialProfileQuestionnaire, InitialProfileResponse
from app.services.onboarding_service import OnboardingService

router = APIRouter()


@router.get("/questions")
def get_onboarding_questions(request: Request):
    """获取由服务端维护的初始画像问卷定义。"""
    service: OnboardingService = request.app.container.onboarding_service()
    return {"questions": service.questionnaire()}


@router.post("/initial-profile", response_model=InitialProfileResponse)
def create_initial_profile(payload: InitialProfileQuestionnaire, request: Request):
    """由入门问卷创建画像，仅返回用户声明已了解节点的诊断题。"""
    service: OnboardingService = request.app.container.onboarding_service()
    try:
        return service.create_initial_profile(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
