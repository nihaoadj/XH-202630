import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import learner, generate, feedback, report
from app.config import get_settings
from app.containers import init_container
from app.db.database import init_database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动与关闭生命周期"""
    # 初始化依赖注入容器
    container = init_container()
    app.container = container
    
    # 初始化数据库
    settings = get_settings()
    if settings.db_type != "memory":
        logger.info(f"检测到 DB_TYPE={settings.db_type}，自动初始化数据库表...")
        init_database()
        logger.info("数据库表初始化完成")
    
    yield


app = FastAPI(
    title="领域知识个性化生成与多智能体协同决策系统",
    description="XH-202630 赛题作品后端 API",
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


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    """统一 HTTPException 错误响应格式"""
    return JSONResponse(
        status_code=exc.status_code,
        content={"status": "error", "message": str(exc.detail), "detail": None},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """统一请求参数校验错误响应格式"""
    return JSONResponse(
        status_code=422,
        content={"status": "error", "message": "请求参数校验失败", "detail": exc.errors()},
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常捕获，避免未处理异常直接暴露堆栈"""
    logger.error(f"Unhandled exception at {request.url.path}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"status": "error", "message": "服务器内部错误，请稍后重试"},
    )


app.include_router(learner.router, prefix="/api/learner", tags=["学习者画像"])
app.include_router(generate.router, prefix="/api/generate", tags=["资源生成"])
app.include_router(feedback.router, prefix="/api/feedback", tags=["学习反馈"])
app.include_router(report.router, prefix="/api/report", tags=["学情报告"])


@app.get("/")
def read_root():
    return {"message": "领域知识个性化生成与多智能体协同决策系统 API"}
