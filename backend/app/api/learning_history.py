from fastapi import APIRouter, HTTPException, Request

from app.models.history_schemas import LearningHistoryTimelineResponse
from app.services.learning_history_service import LearningHistoryService

router = APIRouter()


@router.get("/{learner_id}/timeline", response_model=LearningHistoryTimelineResponse)
def get_learning_history_timeline(learner_id: str, request: Request):
    service: LearningHistoryService = request.app.container.learning_history_service()
    timeline = service.timeline(learner_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return timeline
