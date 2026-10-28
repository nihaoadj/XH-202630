from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.core.health import build_health_report
from app.models.learning_documents.schemas import (
    GenerateRequest,
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
    req: GenerateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
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
