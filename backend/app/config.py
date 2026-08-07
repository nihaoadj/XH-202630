from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from pydantic import SecretStr, field_validator, model_validator
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
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    db_type: str = "sqlite"  # memory | sqlite | postgresql
    database_url: str = "sqlite:///./data/domain_knowledge.db"
    knowledge_base_dir: str = "../knowledge_base/rag_engineering_training"
    vector_store_dir: str = "./chroma_db"
    chroma_collection_prefix: str = "kb"
    # Deprecated compatibility input. During the compatibility window this is
    # interpreted as a prefix, never as one fixed collection shared by all KBs.
    chroma_collection_name: str | None = None
    rerank_enabled: bool = True
    rerank_model: str = "BAAI/bge-reranker-base"
    rerank_model_cache_dir: str = "./data/models"
    rerank_device: str = "cpu"
    rerank_candidate_k: int = 20
    rerank_per_query_k: int = 10
    rerank_batch_size: int = 4
    rerank_max_length: int = 512
    rerank_max_chunks_per_document: int = 2
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

    @model_validator(mode="after")
    def validate_runtime_settings(self):
        legacy_prefix = (self.chroma_collection_name or "").strip()
        if legacy_prefix and "chroma_collection_prefix" not in self.model_fields_set:
            self.chroma_collection_prefix = legacy_prefix
        if not self.chroma_collection_prefix.strip():
            self.chroma_collection_prefix = "kb"

        if self.rerank_enabled:
            if not self.rerank_model.strip():
                raise ValueError("CFG_RERANK_MODEL_MISSING")
            if self.rerank_candidate_k <= 0 or self.rerank_per_query_k <= 0:
                raise ValueError("CFG_RERANK_CANDIDATE_INVALID")
            if self.rerank_batch_size <= 0 or self.rerank_max_length <= 0:
                raise ValueError("CFG_RERANK_RUNTIME_INVALID")
            if self.rerank_max_chunks_per_document <= 0:
                raise ValueError("CFG_RERANK_DIVERSITY_INVALID")

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
