from fastapi import APIRouter, HTTPException, Query, Request

from app.api.dependencies import ensure_profile_access
from app.models.learners.history import LearningHistoryTimelineResponse, LearningJourneyResponse
from app.services.learners.history import LearningHistoryService

router = APIRouter()


@router.get("/{learner_id}/journey", response_model=LearningJourneyResponse)
def get_learning_journey(
    learner_id: str,
    request: Request,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=20, ge=1, le=50),
):
    profile = request.app.container.profile_service().get(learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    service: LearningHistoryService = request.app.container.learning_history_service()
    journey = service.journey(learner_id, offset=offset, limit=limit)
    if journey is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    return journey


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
