import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import diagnosis, evaluation, feedback, generate, knowledge, onboarding, profiles, report, resources, reviews, skills
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
    """应用启动与关闭生命周期"""
    settings = get_settings()
    if settings.db_type == "memory":
        logger.warning(
            "*** EPHEMERAL STORAGE WARNING: DB_TYPE=memory; all repository data "
            "will be lost when this process stops. ***"
        )

    # 初始化依赖注入容器
    container = init_container()
    app.container = container

    # 初始化数据库
    health_overrides = {}
    if settings.db_type != "memory":
        logger.info("检测到 DB_TYPE=%s，自动初始化数据库表...", settings.db_type)
        try:
            init_database()
            logger.info("数据库表初始化完成")
        except Exception:
            logger.error(
                "数据库初始化失败 code=%s type=database_initialization_error",
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
    title="领域知识个性化生成与多智能体协同决策系统",
    description="面向多领域技能学习者的个性化领域知识生成与多智能体协同决策系统 API",
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
    """Map internal failures to a stable response without exposing upstream details."""
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
    """统一 HTTPException 错误响应格式"""
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
    """统一请求参数校验错误响应格式"""
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
    """全局异常捕获，避免未处理异常直接暴露堆栈"""
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


app.include_router(onboarding.router, prefix="/api/onboarding", tags=["初始画像问卷"])
app.include_router(profiles.router, prefix="/api/profiles", tags=["学习者画像"])
app.include_router(generate.router, prefix="/api/generate", tags=["资源生成"])
app.include_router(resources.router, prefix="/api/resources", tags=["资源历史"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["学习反馈"])
app.include_router(report.router, prefix="/api/report", tags=["学情报告"])
app.include_router(skills.router, prefix="/api/skills", tags=["能力图谱"])
app.include_router(diagnosis.router, prefix="/api/diagnosis", tags=["能力诊断"])
app.include_router(knowledge.router, prefix="/api/knowledge", tags=["知识库"])
app.include_router(reviews.router, prefix="/api/reviews", tags=["审核证据"])
app.include_router(evaluation.router, prefix="/api/evaluation", tags=["量化评测"])


@app.get("/")
def read_root():
    return {"message": "领域知识个性化生成与多智能体协同决策系统 API"}


@app.get("/health")
def health(request: Request):
    """Return sanitized readiness without calling external model endpoints."""
    settings = get_settings()
    report = build_health_report(settings)
    request.app.state.health_report = report
    return JSONResponse(
        status_code=503 if report.status == "not_ready" else 200,
        content=report.model_dump(mode="json", exclude_none=True),
    )
