from fastapi import APIRouter, BackgroundTasks, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.config import get_settings
from app.core.health import build_health_report
from app.models.schemas import (
    GenerateRequest,
    GenerationJobCreateResponse,
    GenerationJobListResponse,
    GenerationJobStatusResponse,
)
from app.services.generation_job_service import GenerationJobService
from app.services.profile_service import ProfileService

router = APIRouter()


@router.post("/jobs", response_model=GenerationJobCreateResponse)
def create_generation_job(
    req: GenerateRequest,
    request: Request,
    background_tasks: BackgroundTasks,
):
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
    job = generation_job_service.create_job(learner, req)
    background_tasks.add_task(
        generation_job_service.run_job,
        learner,
        req,
        job.run_id,
        job.batch_id,
    )
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


@router.get("/jobs", response_model=GenerationJobListResponse)
def list_generation_jobs(learner_id: str, request: Request):
    container = request.app.container
    profile_service: ProfileService = container.profile_service()
    learner = ensure_profile_access(request, profile_service.get(learner_id))
    if not learner:
        raise HTTPException(status_code=404, detail="学习者画像不存在")

    generation_job_service: GenerationJobService = container.generation_job_service()
    return generation_job_service.list_jobs(learner_id)
