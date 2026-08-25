"""RAG 入门问卷与初始画像接口。"""
from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import request_user
from app.models.learning_documents.schemas import InitialProfileQuestionnaire, InitialProfileResponse
from app.services.onboarding.onboarding import OnboardingService

router = APIRouter()


@router.get("/questions")
def get_onboarding_questions(request: Request, learning_direction_id: str | None = None):
    """获取由服务端维护的初始画像问卷定义。"""
    service: OnboardingService = request.app.container.onboarding_service()
    try:
        manifest = service.knowledge_service._ensure_knowledge_base(learning_direction_id)
        return {
            "learning_direction_id": manifest["knowledge_base_id"],
            "questions": service.questionnaire(manifest["knowledge_base_id"]),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/initial-profile", response_model=InitialProfileResponse)
def create_initial_profile(payload: InitialProfileQuestionnaire, request: Request):
    """由入门问卷创建画像，并返回服务端按预判阶段抽取的九题初诊。"""
    service: OnboardingService = request.app.container.onboarding_service()
    try:
        return service.create_initial_profile(payload, authenticated_user=request_user(request))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
