import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    admin,
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
    skills,
    users,
)
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
            logger.info("Database tables initialized.")
        except Exception:
            logger.error(
                "Database initialization failed code=%s type=database_initialization_error",
                ErrorCode.STORAGE_DATABASE_UNAVAILABLE.value,
            )
            health_overrides["storage"] = ErrorCode.STORAGE_DATABASE_UNAVAILABLE

    report = build_health_report(
        settings,
        prepare_directories=True,
        overrides=health_overrides,
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


app.include_router(onboarding.router, prefix="/api/onboarding", tags=["onboarding"])
app.include_router(profiles.router, prefix="/api/profiles", tags=["profiles"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(generate.router, prefix="/api/generate", tags=["generate"])
app.include_router(resources.router, prefix="/api/resources", tags=["resources"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["feedback"])
app.include_router(report.router, prefix="/api/report", tags=["report"])
app.include_router(skills.router, prefix="/api/skills", tags=["skills"])
app.include_router(diagnosis.router, prefix="/api/diagnosis", tags=["diagnosis"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["knowledge"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["reviews"])
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["evaluation"])
app.include_router(learning_history.router, prefix="/api/learning-history", tags=["learning-history"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])


@app.get("/")
def read_root():
    return {"message": "Training Pilot API"}


@app.get("/health")
@app.get("/health/ready")
def health(request: Request):
    settings = get_settings()
    report = build_health_report(settings)
    request.app.state.health_report = report
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=report.model_dump(mode="json", exclude_none=True),
    )
