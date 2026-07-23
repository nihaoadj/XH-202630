from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import FeedbackHistoryResponse, FeedbackRequest, FeedbackResponse
from app.services.learner_service import LearnerService
from app.services.feedback_service import FeedbackService

router = APIRouter()


@router.post("/", response_model=FeedbackResponse)
def submit_feedback(req: FeedbackRequest, request: Request):
    """提交学习反馈并触发动态迭代"""
    container = request.app.container
    
    learner_service: LearnerService = container.learner_service()
    profile = learner_service.get(req.learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    response = feedback_service.process_feedback(profile, req)

    # 更新后的画像需要持久化
    learner_service.create_or_update(profile)

    return response


@router.get("/history/{learner_id}", response_model=FeedbackHistoryResponse)
def get_feedback_history(learner_id: str, request: Request):
    """查询学习反馈历史"""
    container = request.app.container

    learner_service: LearnerService = container.learner_service()
    profile = learner_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    items = feedback_service.list_history(learner_id)
    return {
        "learner_id": learner_id,
        "total": len(items),
        "items": items,
    }
