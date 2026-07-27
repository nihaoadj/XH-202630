"""Stable, sanitized application errors and degraded-mode policy."""

from enum import Enum

from app.config import get_settings


class ErrorCode(str, Enum):
    CFG_UNSUPPORTED_PYTHON = "CFG_UNSUPPORTED_PYTHON"
    CFG_INVALID_APP_MODE = "CFG_INVALID_APP_MODE"
    CFG_INVALID_DB_TYPE = "CFG_INVALID_DB_TYPE"
    CFG_DATABASE_URL_MISMATCH = "CFG_DATABASE_URL_MISMATCH"
    CFG_PRODUCTION_DEGRADED_FORBIDDEN = "CFG_PRODUCTION_DEGRADED_FORBIDDEN"
    CFG_PRODUCTION_EPHEMERAL_STORAGE = "CFG_PRODUCTION_EPHEMERAL_STORAGE"
    CFG_LLM_API_KEY_MISSING = "CFG_LLM_API_KEY_MISSING"
    CFG_LLM_API_KEY_PLACEHOLDER = "CFG_LLM_API_KEY_PLACEHOLDER"
    CFG_LLM_ENDPOINT_INVALID = "CFG_LLM_ENDPOINT_INVALID"
    CFG_LLM_MODEL_MISSING = "CFG_LLM_MODEL_MISSING"
    CFG_EMBEDDING_MODEL_MISSING = "CFG_EMBEDDING_MODEL_MISSING"
    EMBEDDING_MODEL_UNAVAILABLE = "EMBEDDING_MODEL_UNAVAILABLE"
    STORAGE_MEMORY_EPHEMERAL = "STORAGE_MEMORY_EPHEMERAL"
    STORAGE_SQLITE_PATH_UNWRITABLE = "STORAGE_SQLITE_PATH_UNWRITABLE"
    STORAGE_DATABASE_UNAVAILABLE = "STORAGE_DATABASE_UNAVAILABLE"
    VECTOR_DIRECTORY_UNWRITABLE = "VECTOR_DIRECTORY_UNWRITABLE"
    VECTOR_COLLECTION_MISSING = "VECTOR_COLLECTION_MISSING"
    VECTOR_COLLECTION_EMPTY = "VECTOR_COLLECTION_EMPTY"
    VECTOR_STORE_UNAVAILABLE = "VECTOR_STORE_UNAVAILABLE"
    RESOURCE_DIRECTORY_UNWRITABLE = "RESOURCE_DIRECTORY_UNWRITABLE"
    GENERATION_DEPENDENCY_UNAVAILABLE = "GENERATION_DEPENDENCY_UNAVAILABLE"
    LLM_UPSTREAM_UNAVAILABLE = "LLM_UPSTREAM_UNAVAILABLE"
    RETRIEVAL_UPSTREAM_UNAVAILABLE = "RETRIEVAL_UPSTREAM_UNAVAILABLE"
    REQUEST_VALIDATION_ERROR = "REQUEST_VALIDATION_ERROR"
    HTTP_ERROR = "HTTP_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"


PUBLIC_MESSAGES = {
    ErrorCode.GENERATION_DEPENDENCY_UNAVAILABLE: "生成依赖当前不可用",
    ErrorCode.LLM_UPSTREAM_UNAVAILABLE: "大模型服务当前不可用",
    ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE: "知识检索服务当前不可用",
    ErrorCode.REQUEST_VALIDATION_ERROR: "请求参数校验失败",
    ErrorCode.INTERNAL_ERROR: "服务器内部错误，请稍后重试",
}


class ApplicationError(Exception):
    """An error safe to map to a stable public response."""

    def __init__(
        self,
        code: ErrorCode,
        public_message: str | None = None,
        status_code: int = 503,
    ):
        self.code = code
        self.public_message = public_message or PUBLIC_MESSAGES.get(code, "服务当前不可用")
        self.status_code = status_code
        super().__init__(code.value)


def require_degraded_generation(code: ErrorCode) -> str:
    """Allow a fallback only when the current non-production mode explicitly opts in."""
    settings = get_settings()
    if settings.app_mode == "production" or not settings.allow_degraded_generation:
        raise ApplicationError(code)
    return code.value
