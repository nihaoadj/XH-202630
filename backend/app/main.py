import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin,
    auth,
    diagnosis,
    evaluation,
    feedback,
    generate,
    knowledge,
    learning_history,
    onboarding,
    profiles,
    report,
    resources,
    reviews,
    runs,
    skills,
    tutor,
    users,
)
from app.api.dependencies import get_current_user
from app.config import get_settings
from app.containers import init_container
from app.core.errors import ApplicationError, ErrorCode
from app.core.health import build_health_report
from app.db.database import init_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.db_type == "memory":
        logger.warning(
            "*** EPHEMERAL STORAGE WARNING: DB_TYPE=memory; all repository data will be lost when this process stops. ***"
        )

    container = init_container()
    app.container = container

    health_overrides = {}
    if settings.db_type != "memory":
        logger.info("Detected DB_TYPE=%s, initializing database tables...", settings.db_type)
        try:
            init_database()
            now = datetime.now(timezone.utc)
            stale_knowledge_base_ids = (
                container.knowledge_catalog().mark_stale_indexing_not_ready(
                    before=now - timedelta(
                        seconds=settings.knowledge_index_stale_seconds
                    ),
                    error_code=ErrorCode.KNOWLEDGE_INDEXING_INTERRUPTED.value,
                )
            )
            if stale_knowledge_base_ids:
                logger.warning(
                    "Marked stale knowledge indexes not_ready count=%s knowledge_base_ids=%s",
                    len(stale_knowledge_base_ids),
                    ",".join(stale_knowledge_base_ids),
                )
            interrupted = container.audit_repository().mark_stale_interrupted(
                before=now,
                occurred_at=now,
            )
            if interrupted:
                logger.warning(
                    "Marked %s expired workflow runs as interrupted",
                    interrupted,
                )
            if settings.db_type == "sqlite":
                stale_job_ids = (
                    container.generation_job_repository().fail_incomplete_before(
                        now,
                        ErrorCode.GENERATION_JOB_INTERRUPTED.value,
                    )
                )
                reconciled_followups = (
                    container.feedback_loop_repository().reconcile_incomplete_followups(
                        stale_child_run_ids=stale_job_ids,
                        error_code=ErrorCode.GENERATION_JOB_INTERRUPTED.value,
                    )
                )
                if stale_job_ids or reconciled_followups:
                    logger.warning(
                        "Reconciled restart state stale_generation_jobs=%s feedback_followups=%s",
                        len(stale_job_ids),
                        reconciled_followups,
                    )
            logger.info("Database tables initialized.")
        except Exception:
            logger.error(
                "Database initialization failed code=%s type=database_initialization_error",
                ErrorCode.STORAGE_DATABASE_UNAVAILABLE.value,
            )
            health_overrides["storage"] = ErrorCode.STORAGE_DATABASE_UNAVAILABLE

    index_status_provider = (
        container.knowledge_catalog().get_index_status
        if hasattr(container, "knowledge_catalog")
        else None
    )
    report = build_health_report(
        settings,
        prepare_directories=True,
        overrides=health_overrides,
        index_status_provider=index_status_provider,
    )
    app.state.health_report = report
    logger.info(
        "Runtime readiness status=%s app_mode=%s storage=%s error_codes=%s",
        report.status,
        report.app_mode,
        report.storage.mode,
        report.error_codes,
    )
    if settings.app_mode == "production" and report.status != "ready":
        raise ApplicationError(ErrorCode.GENERATION_DEPENDENCY_UNAVAILABLE)

    yield


app = FastAPI(
    title="Training Pilot API",
    description="Personalized learning generation and multi-agent collaboration system API",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(ApplicationError)
async def application_exception_handler(request: Request, exc: ApplicationError):
    logger.warning(
        "Application error path=%s code=%s type=%s",
        request.url.path,
        exc.code.value,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": exc.code.value,
            "message": exc.public_message,
            "detail": None,
        },
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "status": "error",
            "code": ErrorCode.HTTP_ERROR.value,
            "message": str(exc.detail),
            "detail": None,
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "status": "error",
            "code": ErrorCode.REQUEST_VALIDATION_ERROR.value,
            "message": "请求参数校验失败",
            "detail": [
                {"loc": error["loc"], "type": error["type"], "msg": error["msg"]}
                for error in exc.errors()
            ],
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception path=%s code=%s type=%s",
        request.url.path,
        ErrorCode.INTERNAL_ERROR.value,
        type(exc).__name__,
    )
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "code": ErrorCode.INTERNAL_ERROR.value,
            "message": "服务器内部错误，请稍后重试",
            "detail": None,
        },
    )


private_api = [Depends(get_current_user)]

app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"], dependencies=private_api)
app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"], dependencies=private_api)
app.include_router(users.router, prefix="/api/users", tags=["users"], dependencies=private_api)
app.include_router(generate.router, prefix="/api/generate", tags=["generate"], dependencies=private_api)
app.include_router(resources.router, prefix="/api/resources", tags=["resources"], dependencies=private_api)
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"], dependencies=private_api)
app.include_router(tutor.router, prefix="/api/tutor", tags=["tutor"], dependencies=private_api)
app.include_router(report.router, prefix="/api/report", tags=["report"], dependencies=private_api)
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(diagnosis.router, prefix="/api/diagnosis", tags=["diagnosis"], dependencies=private_api)
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["reviews"], dependencies=private_api)
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"], dependencies=private_api)
app.include_router(runs.router, prefix="/api/runs", tags=["workflow-runs"], dependencies=private_api)
app.include_router(
    learning_history.router,
    prefix="/api/learning-history",
    tags=["learning-history"],
    dependencies=private_api,
)
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def read_root():
    return {"message": "Training Pilot API"}


@app.get("/health")
@app.get("/health/ready")
def health(request: Request):
    settings = get_settings()
    container = getattr(request.app, "container", None)
    index_status_provider = (
        container.knowledge_catalog().get_index_status
        if container is not None and hasattr(container, "knowledge_catalog")
        else None
    )
    report = build_health_report(
        settings,
        index_status_provider=index_status_provider,
    )
    request.app.state.health_report = report
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=report.model_dump(mode="json", exclude_none=True),
    )
