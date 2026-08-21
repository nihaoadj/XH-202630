from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request

from app.api.dependencies import ensure_profile_access
from app.core.errors import ApplicationError
from app.models.feedback_loop import (
    FeedbackFollowupSelection, FeedbackLoopResult, LearningAttempt,
    LearningAttemptSubmit, LearningPath,
)
from app.models.schemas import (
    BatchAttemptSubmitRequest,
    BatchEvaluationSessionResponse,
    ResourceEvaluationSessionResponse,
    RunAttemptSubmitRequest,
    RunEvaluationSessionResponse,
)
from app.services.feedback_service import FeedbackService
from app.services.knowledge_service import KnowledgeService
from app.services.profile_service import ProfileService
from app.services.resource_service import ResourceService

router = APIRouter()


@router.post("/attempts", response_model=FeedbackLoopResult)
def submit_learning_attempt(
    payload: LearningAttemptSubmit,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Formal P0-07 feedback entry with idempotency and profile-version CAS."""

    container = request.app.container
    profile = ensure_profile_access(request, container.profile_service().get(payload.learner_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    resource = container.resource_service().get(payload.source_resource_id)
    if resource is None or resource.learner_id != payload.learner_id:
        raise HTTPException(status_code=404, detail="资源不存在")
    service: FeedbackService = container.feedback_service()

    def schedule(learner, generate_request, run_id):
        if service.generation_job_service is None:
            return
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


@router.post("/attempts/run/submit", response_model=FeedbackLoopResult)
def submit_run_attempt(
    payload: RunAttemptSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = ensure_profile_access(request, profile_service.get(payload.learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resources = resource_service.list_by_learner_with_filter(payload.learner_id, run_id=payload.run_id)
    if not resources:
        raise HTTPException(status_code=404, detail="任务资源不存在")

    def schedule(learner, generate_request, run_id):
        if feedback_service.generation_job_service is None:
            return
        background_tasks.add_task(
            feedback_service.generation_job_service.run_job,
            learner,
            generate_request,
            run_id,
        )

    try:
        return feedback_service.submit_run_attempt(
            profile,
            payload.run_id,
            resources,
            payload,
            knowledge_service,
            schedule_followup=schedule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/attempts/batch/submit", response_model=FeedbackLoopResult)
def submit_batch_attempt(
    payload: BatchAttemptSubmitRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Score all resources in one learning batch as one feedback event."""
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = ensure_profile_access(request, profile_service.get(payload.learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resources = [
        resource
        for resource in resource_service.list_by_learner(payload.learner_id)
        if (resource.batch_id or resource.run_id) == payload.batch_id
    ]
    if not resources:
        raise HTTPException(status_code=404, detail="资源批次不存在")
    source_resource = next(
        (resource for resource in resources if resource.resource_id == payload.source_resource_id),
        resources[0],
    )
    source_run_id = source_resource.run_id or payload.batch_id
    run_payload = RunAttemptSubmitRequest(
        learner_id=payload.learner_id,
        run_id=source_run_id,
        source_resource_id=source_resource.resource_id,
        path_node_id=payload.path_node_id,
        idempotency_key=payload.idempotency_key,
        expected_profile_version=payload.expected_profile_version,
        started_at=payload.started_at,
        submitted_at=payload.submitted_at,
        duration_ms=payload.duration_ms,
        hint_count=payload.hint_count,
        answers=payload.answers,
        metadata={**payload.metadata, "session_id": payload.batch_id},
    )

    def schedule(learner, generate_request, run_id):
        if feedback_service.generation_job_service is not None:
            background_tasks.add_task(
                feedback_service.generation_job_service.run_job,
                learner,
                generate_request,
                run_id,
            )

    try:
        return feedback_service.submit_run_attempt(
            profile,
            source_run_id,
            resources,
            run_payload,
            knowledge_service,
            tutor_batch_id=payload.batch_id,
            schedule_followup=schedule,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/followups/select", response_model=FeedbackLoopResult)
def select_feedback_followup(
    payload: FeedbackFollowupSelection,
    request: Request,
    background_tasks: BackgroundTasks,
):
    """Create the next generation job only after the learner selects an option."""
    container = request.app.container
    profile = ensure_profile_access(request, container.profile_service().get(payload.learner_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    service: FeedbackService = container.feedback_service()

    def schedule(learner, generate_request, run_id):
        if service.generation_job_service is not None:
            background_tasks.add_task(service.generation_job_service.run_job, learner, generate_request, run_id)

    try:
        return service.choose_followup(profile, payload, schedule_followup=schedule)
    except ApplicationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code.value) from exc


@router.get("/attempts/{learner_id}", response_model=list[LearningAttempt])
def list_learning_attempts(
    learner_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    profile = ensure_profile_access(request, request.app.container.profile_service().get(learner_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    return request.app.container.feedback_service().list_attempts(learner_id, limit)


@router.get("/results/{learner_id}", response_model=list[FeedbackLoopResult])
def list_feedback_results(
    learner_id: str,
    request: Request,
    limit: int = Query(default=20, ge=1, le=100),
):
    profile = ensure_profile_access(request, request.app.container.profile_service().get(learner_id))
    if profile is None:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    return request.app.container.feedback_service().list_results(learner_id, limit)


@router.get("/path/{learner_id}", response_model=LearningPath)
def get_current_learning_path(learner_id: str, request: Request):
    profile = ensure_profile_access(request, request.app.container.profile_service().get(learner_id))
    if profile is None:
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

    profile = ensure_profile_access(request, profile_service.get(learner_id))
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

    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")

    resources = resource_service.list_by_learner_with_filter(learner_id, run_id=run_id)
    if not resources:
        raise HTTPException(status_code=404, detail="任务资源不存在")

    return feedback_service.build_run_evaluation_session(profile, run_id, resources, knowledge_service)


@router.get("/evaluation/batch/{learner_id}/{batch_id}", response_model=BatchEvaluationSessionResponse)
def get_batch_evaluation(learner_id: str, batch_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    resource_service: ResourceService = container.resource_service()
    feedback_service: FeedbackService = container.feedback_service()
    knowledge_service: KnowledgeService = container.knowledge_service()

    profile = ensure_profile_access(request, profile_service.get(learner_id))
    if not profile:
        raise HTTPException(status_code=404, detail="学习画像不存在")
    resources = [
        resource
        for resource in resource_service.list_by_learner(learner_id)
        if (resource.batch_id or resource.run_id) == batch_id
    ]
    if not resources:
        raise HTTPException(status_code=404, detail="资源批次不存在")
    return feedback_service.build_batch_evaluation_session(profile, batch_id, resources, knowledge_service)
