from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import FeedbackRequest, FeedbackResponse
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
