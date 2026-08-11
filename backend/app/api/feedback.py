from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from app.models.schemas import (
    FeedbackHistoryResponse,
    FeedbackRequest,
    FeedbackResponse,
    ResourceEvaluationSessionResponse,
    ResourceEvaluationSubmitRequest,
    ResourceEvaluationSubmitResponse,
    RunEvaluationSessionResponse,
    RunEvaluationSubmitRequest,
    RunEvaluationSubmitResponse,
)
from app.services.feedback_service import FeedbackService
from app.services.knowledge_service import KnowledgeService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService
from app.models.feedback_loop import FeedbackLoopResult, LearningAttempt, LearningAttemptSubmit, LearningPath

router = APIRouter()


@router.post("/attempts", response_model=FeedbackLoopResult)
def submit_learning_attempt(
    payload: LearningAttemptSubmit,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Formal P0-07 feedback entry with idempotency and profile-version CAS."""

    container = request.app.container
    profile = container.profile_service().get(payload.learner_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    resource = container.resource_service().get(payload.source_resource_id)
    if resource is None or resource.learner_id != payload.learner_id:
        raise HTTPException(status_code=404, detail="资源不存在")
    service: FeedbackService = container.feedback_service()

    def schedule(learner, generate_request, run_id):
        background_tasks.add_task(
            service.generation_job_service.run_job,
            learner,
            generate_request,
            run_id,
        )

    return service.process_learning_attempt(
        profile,
        resource,
        payload,
        schedule_followup=schedule,
    )


@router.get("/attempts/{learner_id}", response_model=list[LearningAttempt])
def list_learning_attempts(
    learner_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    if request.app.container.profile_service().get(learner_id) is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    return request.app.container.feedback_service().list_attempts(learner_id, limit)


@router.get("/path/{learner_id}", response_model=LearningPath)
def get_current_learning_path(learner_id: str, request: Request):
    if request.app.container.profile_service().get(learner_id) is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    path = request.app.container.feedback_service().get_current_path(learner_id)
    if path is None:
        raise HTTPException(status_code=404, detail="学习路径不存在")
    return path


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


@router.get("/evaluation/run/{learner_id}/{run_id}", response_model=RunEvaluationSessionResponse)
def get_run_evaluation(learner_id: str, run_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = profile_service.get(learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resources = resource_service.list_by_learner_with_filter(learner_id, run_id=run_id)
    if not resources:
        raise HTTPException(status_code=404, detail="任务资源不存在")

    return feedback_service.build_run_evaluation_session(profile, run_id, resources, knowledge_service)


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


@router.post("/evaluation/run/submit", response_model=RunEvaluationSubmitResponse)
def submit_run_evaluation(payload: RunEvaluationSubmitRequest, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = profile_service.get(payload.learner_id)
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resources = resource_service.list_by_learner_with_filter(payload.learner_id, run_id=payload.run_id)
    if not resources:
        raise HTTPException(status_code=404, detail="任务资源不存在")

    try:
        response = feedback_service.submit_run_evaluation_feedback(
            profile,
            payload.run_id,
            resources,
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
