from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.core.health import build_health_report
from app.models.learning_documents.schemas import (
    GenerateRequest,
    GenerateCreateRequest,
    GenerationJobCreateResponse,
    GenerationJobListResponse,
    GenerationJobStatusResponse,
)
from app.models.learning_documents.types import FEEDBACK_ONLY_RESOURCE_TYPES
from app.core.security.errors import ApplicationError, ErrorCode
from app.services.generation.jobs import GenerationJobService
from app.services.generation.dispatch import schedule_generation, submission_identity
from app.services.learners.profiles import ProfileService

router = APIRouter()


@router.post("/jobs", response_model=GenerationJobCreateResponse)
def create_generation_job(
    req: GenerateCreateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
    if set(req.constraints) - {"supplemental_requirements"}:
        raise ApplicationError(ErrorCode.GENERATION_TARGET_INVALID, status_code=422)
    if set(req.resource_types) & set(FEEDBACK_ONLY_RESOURCE_TYPES):
        raise ApplicationError(ErrorCode.FEEDBACK_ONLY_RESOURCE_TYPE, status_code=422)
    report = build_health_report(get_settings())
    if report.status == "not_ready":
        detail = "生成依赖未就绪"
        if report.error_codes:
            detail = f"{detail}：{', '.join(report.error_codes)}"
        raise HTTPException(status_code=503, detail=detail)

    container = request.app.container

    profile_service: ProfileService = container.profile_service()
    learner = ensure_profile_access(request, profile_service.get(req.learner_id))
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_job_service: GenerationJobService = container.generation_job_service()
    identity = submission_identity(learner, req, getattr(request, "headers", {}).get("Idempotency-Key"), "generation")
    job = generation_job_service.create_job(learner, req, **identity)
    schedule_generation(generation_job_service, background_tasks, learner, req, job.run_id, job.batch_id)
    return job


@router.get("/jobs/{run_id}", response_model=GenerationJobStatusResponse)
def get_generation_job(run_id: str, request: Request):
    generation_job_service: GenerationJobService = request.app.container.generation_job_service()
    job = generation_job_service.get_job(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    profile = request.app.container.profile_service().get(job.learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    return job


@router.post("/jobs/{run_id}/resource-specs/{resource_spec_id}/representations/{representation}/retry",
             response_model=GenerationJobCreateResponse)
def retry_resource_representation(run_id: str, resource_spec_id: str, representation: str,
                                  request: Request, background_tasks: BackgroundTasks):
    container = request.app.container
    service: GenerationJobService = container.generation_job_service()
    source = service.get_job(run_id)
    if source is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    learner = ensure_profile_access(request, container.profile_service().get(source.learner_id))
    if learner is None:
        raise HTTPException(status_code=404, detail="生成任务不存在")
    job, frozen_request = service.create_resource_retry(
        learner, run_id, resource_spec_id, representation,
        idempotency_key=request.headers.get("Idempotency-Key"),
        round_uow_factory=getattr(container, "round_uow_factory", None),
    )
    schedule_generation(service, background_tasks, learner, frozen_request, job.run_id, job.batch_id)
    return job


@router.get("/jobs", response_model=GenerationJobListResponse)
def list_generation_jobs(learner_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    learner = ensure_profile_access(request, profile_service.get(learner_id))
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_job_service: GenerationJobService = container.generation_job_service()
    return generation_job_service.list_jobs(learner_id)


from app.models.feedback.rounds import GenerateRoundCreateRequestV1, GenerationCapabilitiesV1, RoundCreationResponseV1
from app.api.feedback.rounds import schedule_round


@router.get("/capabilities", response_model=GenerationCapabilitiesV1)
def generation_capabilities(request: Request):
    settings = request.app.container.runtime_settings()
    return GenerationCapabilitiesV1(round_creation_enabled=settings.learning_round_creation_enabled,
                                    round_query_available=True, round_recovery_available=True)


@router.post("/rounds", response_model=RoundCreationResponseV1, status_code=202)
def create_round(payload: GenerateRoundCreateRequestV1, request: Request, background_tasks: BackgroundTasks):
    learner = ensure_profile_access(request, request.app.container.profile_service().get(payload.learner_id))
    if learner is None:
        raise ApplicationError(ErrorCode.ROUND_SELECTION_INVALID, status_code=404)
    service = request.app.container.round_learning_service()
    result = service.create(learner, payload)
    schedule_round(service, learner, result, background_tasks)
    return result
