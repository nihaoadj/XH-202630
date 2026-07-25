from functools import lru_cache
from pathlib import Path

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
    llm_api_key: str = ""
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    llm_model: str = "qwen-max"
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    db_type: str = "sqlite"  # memory | sqlite | postgresql
    database_url: str = "sqlite:///./data/domain_knowledge.db"
    knowledge_base_dir: str = "../knowledge_base/rag_engineering_training"
    vector_store_dir: str = "./chroma_db"
    resources_dir: str = "./data/generated_resources"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    debug: bool = True

    model_config = SettingsConfigDict(env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8")


@lru_cache()
def get_settings() -> Settings:
    return Settings()
