from fastapi import APIRouter, HTTPException, Request

from app.models.schemas import (
    FeedbackHistoryResponse,
    FeedbackRequest,
    FeedbackResponse,
    ResourceEvaluationSessionResponse,
    ResourceEvaluationSubmitRequest,
    ResourceEvaluationSubmitResponse,
)
from app.services.feedback_service import FeedbackService
from app.services.knowledge_service import KnowledgeService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService

router = APIRouter()


@router.get("/evaluation/{learner_id}/{resource_id}", response_model=ResourceEvaluationSessionResponse)
def get_resource_evaluation(learner_id: str, resource_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = profile_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resource = resource_service.get(resource_id)
    if not resource or resource.learner_id != learner_id:
        raise HTTPException(status_code=404, detail="资源不存在")

    return feedback_service.build_evaluation_session(profile, resource, knowledge_service)


@router.post("/evaluation/submit", response_model=ResourceEvaluationSubmitResponse)
def submit_resource_evaluation(payload: ResourceEvaluationSubmitRequest, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = profile_service.get(payload.learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resource = resource_service.get(payload.resource_id)
    if not resource or resource.learner_id != payload.learner_id:
        raise HTTPException(status_code=404, detail="资源不存在")

    try:
        response = feedback_service.submit_evaluation_feedback(
            profile,
            resource,
            payload,
            knowledge_service,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if profile_service.save_existing_profile(profile) is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    return response


@router.post("/", response_model=FeedbackResponse)
def submit_feedback(req: FeedbackRequest, request: Request):
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = profile_service.get(req.learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    response = feedback_service.process_feedback(profile, req)

    if profile_service.save_existing_profile(profile) is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    return response


@router.get("/history/{learner_id}", response_model=FeedbackHistoryResponse)
def get_feedback_history(learner_id: str, request: Request):
    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    profile = profile_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    feedback_service: FeedbackService = container.feedback_service()
    items = feedback_service.list_history(learner_id)
    return {
        "learner_id": learner_id,
        "total": len(items),
        "items": items,
    }
