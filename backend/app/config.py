from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_DIR.parent


def resolve_backend_path(path: str | Path) -> Path:
    """Resolve relative runtime paths against the backend directory."""
    target = Path(path)
    if target.is_absolute():
        return target
    return (BACKEND_DIR / target).resolve()


class Settings(BaseSettings):
    """应用配置，自动从 .env 文件加载"""
    app_mode: str = "development"
    allow_degraded_generation: bool = False
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-max"
    llm_request_timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    llm_workflow_timeout_seconds: float = Field(default=105.0, gt=0, le=600)
    llm_max_attempts: int = Field(default=2, ge=1, le=3)
    llm_retry_base_delay_seconds: float = Field(default=0.5, ge=0, le=30)
    llm_retry_max_delay_seconds: float = Field(default=3.0, ge=0, le=60)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    llm_generator_max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    llm_structured_output_mode: str = "auto"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    retrieval_top_k_default: int = Field(default=3, ge=1, le=10)
    retrieval_max_queries: int = Field(default=6, ge=1, le=10)
    retrieval_max_evidence: int = Field(default=8, ge=1, le=20)
    retrieval_min_evidence: int = Field(default=1, ge=1, le=20)
    retrieval_min_normalized_score: float = Field(default=0.35, ge=0, le=1)
    evidence_max_excerpt_chars: int = Field(default=1200, ge=100, le=10000)
    workflow_run_lease_seconds: int = Field(default=180, ge=30, le=3600)
    workflow_checkpoint_max_bytes: int = Field(default=65536, ge=4096, le=1048576)
    workflow_timeline_default_limit: int = Field(default=100, ge=1, le=500)
    workflow_timeline_max_limit: int = Field(default=500, ge=1, le=1000)
    vector_distance_metric: str = "cosine"
    db_type: str = "sqlite"  # memory | sqlite | postgresql
    database_url: str = "sqlite:///./data/domain_knowledge.db"
    knowledge_base_dir: str = "../knowledge_base/rag_engineering_training"
    vector_store_dir: str = "./chroma_db"
    chroma_collection_prefix: str = "kb"
    # Deprecated compatibility input. During the compatibility window this is
    # interpreted as a prefix, never as one fixed collection shared by all KBs.
    chroma_collection_name: str | None = None
    resources_dir: str = "./data/generated_resources"
    admin_health_token: SecretStr = SecretStr("")
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = False
    sql_echo: bool = False

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    @field_validator("app_mode")
    @classmethod
    def validate_app_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"development", "demo", "production"}:
            raise ValueError("CFG_INVALID_APP_MODE")
        return normalized

    @field_validator("db_type")
    @classmethod
    def validate_db_type(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"memory", "sqlite", "postgresql"}:
            raise ValueError("CFG_INVALID_DB_TYPE")
        return normalized

    @field_validator("llm_structured_output_mode")
    @classmethod
    def validate_llm_structured_output_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "json_schema", "function_calling", "json_mode", "text"}:
            raise ValueError("CFG_INVALID_LLM_STRUCTURED_OUTPUT_MODE")
        return normalized

    @field_validator("vector_distance_metric")
    @classmethod
    def validate_vector_distance_metric(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized != "cosine":
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY")
        return normalized

    @field_validator(
        "retrieval_top_k_default",
        "retrieval_max_queries",
        "retrieval_max_evidence",
        "retrieval_min_evidence",
        "evidence_max_excerpt_chars",
        mode="before",
    )
    @classmethod
    def validate_retrieval_integer_policy(cls, value, info):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY") from None
        bounds = {
            "retrieval_top_k_default": (1, 10),
            "retrieval_max_queries": (1, 10),
            "retrieval_max_evidence": (1, 20),
            "retrieval_min_evidence": (1, 20),
            "evidence_max_excerpt_chars": (100, 10000),
        }
        minimum, maximum = bounds[info.field_name]
        if not normalized.is_integer() or not minimum <= normalized <= maximum:
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY")
        return value

    @field_validator("retrieval_min_normalized_score", mode="before")
    @classmethod
    def validate_retrieval_score_policy(cls, value):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY") from None
        if not 0 <= normalized <= 1:
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY")
        return value

    @field_validator(
        "llm_request_timeout_seconds",
        "llm_workflow_timeout_seconds",
        mode="before",
    )
    @classmethod
    def validate_llm_timeout_value(cls, value, info):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_LLM_TIMEOUT") from None
        maximum = 120 if info.field_name == "llm_request_timeout_seconds" else 600
        if normalized <= 0 or normalized > maximum:
            raise ValueError("CFG_INVALID_LLM_TIMEOUT")
        return value

    @field_validator(
        "llm_max_attempts",
        "llm_retry_base_delay_seconds",
        "llm_retry_max_delay_seconds",
        mode="before",
    )
    @classmethod
    def validate_llm_retry_value(cls, value, info):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_LLM_RETRY_POLICY") from None
        if info.field_name == "llm_max_attempts":
            if not normalized.is_integer() or not 1 <= normalized <= 3:
                raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        else:
            maximum = 30 if info.field_name == "llm_retry_base_delay_seconds" else 60
            if normalized < 0 or normalized > maximum:
                raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        return value

    @field_validator(
        "llm_max_output_tokens",
        "llm_generator_max_output_tokens",
        mode="before",
    )
    @classmethod
    def validate_llm_token_limit(cls, value):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_LLM_TOKEN_LIMIT") from None
        if not normalized.is_integer() or not 256 <= normalized <= 65536:
            raise ValueError("CFG_INVALID_LLM_TOKEN_LIMIT")
        return value

    @model_validator(mode="after")
    def validate_runtime_settings(self):
        legacy_prefix = (self.chroma_collection_name or "").strip()
        if legacy_prefix and "chroma_collection_prefix" not in self.model_fields_set:
            self.chroma_collection_prefix = legacy_prefix
        if not self.chroma_collection_prefix.strip():
            self.chroma_collection_prefix = "kb"

        if self.llm_workflow_timeout_seconds <= self.llm_request_timeout_seconds:
            raise ValueError("CFG_INVALID_LLM_TIMEOUT")
        if self.llm_retry_max_delay_seconds < self.llm_retry_base_delay_seconds:
            raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        if self.retrieval_min_evidence > self.retrieval_max_evidence:
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY")

        if self.db_type == "sqlite" and not self.database_url.startswith("sqlite:///"):
            raise ValueError("CFG_DATABASE_URL_MISMATCH")
        if self.db_type == "postgresql" and not self.database_url.startswith(
            ("postgresql://", "postgresql+")
        ):
            raise ValueError("CFG_DATABASE_URL_MISMATCH")

        if self.app_mode != "production":
            return self

        if self.allow_degraded_generation:
            raise ValueError("CFG_PRODUCTION_DEGRADED_FORBIDDEN")
        if self.db_type == "memory":
            raise ValueError("CFG_PRODUCTION_EPHEMERAL_STORAGE")

        api_key = self.llm_api_key.get_secret_value().strip()
        if not api_key:
            raise ValueError("CFG_LLM_API_KEY_MISSING")
        if is_placeholder_api_key(api_key):
            raise ValueError("CFG_LLM_API_KEY_PLACEHOLDER")
        if not is_valid_http_url(self.llm_base_url):
            raise ValueError("CFG_LLM_ENDPOINT_INVALID")
        if not self.llm_model.strip():
            raise ValueError("CFG_LLM_MODEL_MISSING")
        if not self.embedding_model.strip():
            raise ValueError("CFG_EMBEDDING_MODEL_MISSING")
        return self


def is_placeholder_api_key(value: str) -> bool:
    """Return True for documented/template API key values without logging them."""
    normalized = value.strip().lower()
    return normalized in {
        "your_api_key_here",
        "your-api-key-here",
        "changeme",
        "change_me",
        "replace_me",
        "replace-with-real-key",
    }


def is_valid_http_url(value: str) -> bool:
    parsed = urlparse(value.strip())
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


@lru_cache()
def get_settings() -> Settings:
    return Settings()
