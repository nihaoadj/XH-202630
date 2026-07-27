from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import FeedbackHistoryResponse, FeedbackRequest, FeedbackResponse
from app.services.profile_service import ProfileService
from app.services.feedback_service import FeedbackService

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
def submit_feedback(req: FeedbackRequest, request: Request):
    """提交学习反馈并触发动态迭代"""
    container = request.app.container
    
    profile_service: ProfileService = container.profile_service()
    profile = profile_service.get(req.learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    response = feedback_service.process_feedback(profile, req)

    # 反馈只更新已由问卷建立的画像，不承担首次创建职责。
    if profile_service.save_existing_profile(profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    return response


@router.get("/history/{learner_id}", response_model=FeedbackHistoryResponse)
def get_feedback_history(learner_id: str, request: Request):
    """查询学习反馈历史"""
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = profile_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    items = feedback_service.list_history(learner_id)
    return {
        "learner_id": learner_id,
        "total": len(items),
        "items": items,
    }
