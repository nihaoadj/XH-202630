from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.models.history_schemas import LearningHistoryTimelineResponse
from app.services.learning_history_service import LearningHistoryService

router = APIRouter()


@router.get("/{learner_id}/timeline", response_model=LearningHistoryTimelineResponse)
def get_learning_history_timeline(learner_id: str, request: Request):
    profile = request.app.container.profile_service().get(learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    service: LearningHistoryService = request.app.container.learning_history_service()
    timeline = service.timeline(learner_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return timeline
