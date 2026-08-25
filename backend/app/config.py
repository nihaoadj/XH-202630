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
    # AI is the normal courseware authoring path.  ``courseware_ai_enabled``
    # remains as a deployment-owned emergency switch for older environments;
    # it no longer makes deterministic generation the default product mode.
    courseware_ai_enabled: bool = True
    courseware_generation_mode: str = "ai_first"
    # Deployment-owned: callers cannot downgrade a strict release gate.
    courseware_release_policy: str = "resilient"
    courseware_auto_revision_max_attempts: int = Field(default=3, ge=0, le=5)
    courseware_scene_lease_seconds: int = Field(default=120, ge=30, le=900)
    courseware_auto_review_max_seconds: int = Field(default=180, ge=10, le=900)
    courseware_total_llm_token_budget: int = Field(default=73728, ge=256, le=262144)
    courseware_total_run_timeout_seconds: int = Field(default=1050, ge=30, le=3600)
    courseware_planner_token_budget: int = Field(default=8192, ge=0, le=262144)
    courseware_scene_composition_token_budget: int = Field(default=40960, ge=0, le=262144)
    courseware_scene_call_max_tokens: int = Field(default=4096, ge=256, le=65536)
    courseware_quality_review_token_budget: int = Field(default=8192, ge=0, le=262144)
    courseware_revision_token_budget: int = Field(default=16384, ge=0, le=262144)
    courseware_quality_review_reserved_tokens: int = Field(default=8192, ge=0, le=262144)
    courseware_revision_reserved_tokens: int = Field(default=16384, ge=0, le=262144)
    courseware_planner_max_seconds: float = Field(default=90.0, ge=0, le=3600)
    courseware_scene_composition_max_seconds: float = Field(default=600.0, ge=0, le=3600)
    courseware_quality_review_max_seconds: float = Field(default=120.0, ge=0, le=3600)
    courseware_revision_max_seconds: float = Field(default=180.0, ge=0, le=3600)
    courseware_quality_review_reserved_seconds: float = Field(default=120.0, ge=0, le=3600)
    courseware_revision_reserved_seconds: float = Field(default=180.0, ge=0, le=3600)
    courseware_worker_enabled: bool = False
    courseware_worker_poll_seconds: float = Field(default=2.0, gt=0.1, le=60)
    courseware_worker_batch_size: int = Field(default=1, ge=1, le=100)
    courseware_input_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0, le=1000.0)
    courseware_output_cost_per_1k_tokens: float = Field(default=0.0, ge=0.0, le=1000.0)
    # Live acceptance is opt-in and has its own explicit, versioned contract.
    # Empty defaults intentionally make an incomplete live job non-runnable.
    courseware_live_model_config_version: int = Field(default=1, ge=1, le=10)
    courseware_live_model_provider: str = ""
    courseware_live_model_base_url: str = ""
    courseware_live_model: str = ""
    courseware_live_structured_output_mode: str = ""
    courseware_live_timeout_seconds: float | None = Field(default=None, gt=0, le=300)
    courseware_live_max_attempts: int | None = Field(default=None, ge=1, le=3)
    courseware_live_retry_base_delay_seconds: float | None = Field(default=None, ge=0, le=30)
    courseware_live_retry_max_delay_seconds: float | None = Field(default=None, ge=0, le=60)
    courseware_live_input_price_per_1k_tokens: float | None = Field(default=None, ge=0, le=1000)
    courseware_live_output_price_per_1k_tokens: float | None = Field(default=None, ge=0, le=1000)
    courseware_live_price_currency: str = ""
    courseware_live_price_version: str = ""
    courseware_live_price_effective_date: str = ""
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    # Deliberately opt in to a proxy only when one is known to be usable.
    # The transport otherwise ignores Windows/system proxy discovery.
    llm_proxy_url: str | None = None
    llm_model: str = "qwen-max"
    llm_thinking_mode: str = "auto"

    @field_validator("llm_proxy_url", mode="before")
    @classmethod
    def normalize_optional_proxy_url(cls, value):
        """Treat an empty environment variable as direct model access."""

        if value is None:
            return None
        normalized = str(value).strip()
        return normalized or None
    llm_request_timeout_seconds: float = Field(default=120.0, gt=0, le=300)
    # Claim audits inspect long generated resources and need a separate,
    # bounded budget instead of inheriting the generic auxiliary-node limit.
    claim_request_timeout_seconds: float = Field(default=300.0, gt=0, le=600)
    # Resource-oriented runs include generation and review/claim evaluation.
    llm_workflow_timeout_seconds: float = Field(default=1200.0, gt=0, le=1800)
    llm_max_attempts: int = Field(default=2, ge=1, le=3)
    claim_max_attempts: int = Field(default=3, ge=1, le=3)
    claim_schema_repair_attempts: int = Field(default=2, ge=1, le=3)
    # Resource generation produces the user-facing artifact. It receives one
    # additional bounded recovery attempt for empty provider responses, while
    # supporting nodes (review/diagnosis/claim checks) retain the global limit.
    llm_resource_generation_max_attempts: int = Field(default=2, ge=1, le=3)
    llm_retry_base_delay_seconds: float = Field(default=0.5, ge=0, le=30)
    llm_retry_max_delay_seconds: float = Field(default=3.0, ge=0, le=60)
    llm_max_output_tokens: int = Field(default=4096, ge=256, le=65536)
    claim_max_output_tokens: int = Field(default=16384, ge=2048, le=65536)
    # Kept for compatibility with existing deployments.  New resource agents
    # use the explicit per-resource settings below.
    llm_generator_max_output_tokens: int = Field(default=8192, ge=256, le=65536)
    llm_resource_generator_max_input_tokens: int = Field(
        default=32768,
        ge=1024,
        le=262144,
    )
    llm_resource_generator_max_output_tokens: int = Field(
        # Lecture and assessment DTOs have compact, product-sized caps.  This
        # budget is deliberately below the long HTML-guide budget so a model
        # that ignores the requested format reaches compact recovery promptly.
        default=32768,
        ge=8192,
        le=65536,
    )
    # Lecture notes have a bounded long-form Markdown contract. Keep this
    # separate from the generic resource allowance so a slow, complete lecture
    # is not cut off at the normal request timeout or allowed to consume the
    # generic long-document budget. The default preserves the deployed 32k
    # ceiling while allowing an independent lecture-specific setting later.
    text_resource_request_timeout_seconds: float = Field(default=240.0, gt=0, le=600)
    text_resource_max_output_tokens: int = Field(default=32768, ge=4096, le=65536)
    practice_guide_request_timeout_seconds: float = Field(default=300.0, gt=0, le=600)
    practice_guide_max_output_tokens: int = Field(default=49152, ge=8192, le=65536)
    llm_structured_output_mode: str = "auto"
    tutor_llm_timeout_seconds: float = Field(default=25.0, gt=0, le=120)
    tutor_max_output_tokens: int = Field(default=2048, ge=256, le=8192)
    tutor_max_context_turns: int = Field(default=6, ge=1, le=12)
    tutor_max_evidence_items: int = Field(default=4, ge=1, le=8)
    tutor_max_hint_level: int = Field(default=3, ge=0, le=3)
    embedding_model: str = "BAAI/bge-large-zh-v1.5"
    # The embedding model is part of the local runtime contract.  Do not turn
    # a generation request into a Hugging Face network dependency after a
    # restart; model provisioning is an explicit deployment step.
    embedding_local_files_only: bool = True
    retrieval_top_k_default: int = Field(default=3, ge=1, le=10)
    retrieval_max_queries: int = Field(default=6, ge=1, le=10)
    retrieval_max_evidence: int = Field(default=8, ge=1, le=20)
    retrieval_min_evidence: int = Field(default=1, ge=1, le=20)
    retrieval_min_normalized_score: float = Field(default=0.35, ge=0, le=1)
    evidence_max_excerpt_chars: int = Field(default=1200, ge=100, le=10000)
    workflow_run_lease_seconds: int = Field(default=1260, ge=30, le=3600)
    resource_worker_max_concurrency: int = Field(default=2, ge=1, le=4)
    resource_continuation_max_items: int = Field(default=12, ge=1, le=100)
    resource_continuation_summary_max_chars: int = Field(
        default=600,
        ge=100,
        le=4000,
    )
    workflow_checkpoint_max_bytes: int = Field(default=65536, ge=4096, le=1048576)
    workflow_timeline_default_limit: int = Field(default=100, ge=1, le=500)
    workflow_timeline_max_limit: int = Field(default=500, ge=1, le=1000)
    workflow_sse_poll_interval_seconds: float = Field(default=0.5, ge=0.05, le=10)
    workflow_sse_heartbeat_seconds: float = Field(default=15.0, ge=0.1, le=300)
    workflow_sse_event_page_size: int = Field(default=100, ge=1, le=500)
    # Report streaming is independent from durable workflow-event streaming.
    report_sse_poll_interval_seconds: float = Field(default=2.0, ge=0.1, le=60)
    report_sse_heartbeat_seconds: float = Field(default=15.0, ge=1, le=300)
    vector_distance_metric: str = "cosine"
    db_type: str = "sqlite"  # memory | sqlite | postgresql
    database_url: str = "sqlite:///./data/domain_knowledge.db"
    knowledge_base_dir: str = "../knowledge_base/rag_engineering_training"
    vector_store_dir: str = "./chroma_db"
    chroma_collection_prefix: str = "kb"
    # Deprecated compatibility input. During the compatibility window this is
    # interpreted as a prefix, never as one fixed collection shared by all KBs.
    chroma_collection_name: str | None = None
    knowledge_index_stale_seconds: int = Field(default=900, ge=30, le=86400)
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
    auth_jwt_secret: SecretStr = SecretStr("development-only-change-me")
    auth_jwt_algorithm: str = "HS256"
    auth_token_expire_minutes: int = 480
    auth_cookie_name: str = "training_pilot_token"
    auth_cookie_secure: bool = False
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

    @field_validator("courseware_release_policy")
    @classmethod
    def validate_courseware_release_policy(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"strict", "resilient"}:
            raise ValueError("CFG_INVALID_COURSEWARE_RELEASE_POLICY")
        return normalized

    @field_validator("courseware_generation_mode")
    @classmethod
    def validate_courseware_generation_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"ai_first", "offline_eval", "emergency_degraded"}:
            raise ValueError("CFG_INVALID_COURSEWARE_GENERATION_MODE")
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

    @field_validator("llm_thinking_mode")
    @classmethod
    def validate_llm_thinking_mode(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"auto", "enabled", "disabled"}:
            raise ValueError("CFG_INVALID_LLM_THINKING_MODE")
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
        "claim_request_timeout_seconds",
        "llm_workflow_timeout_seconds",
        "tutor_llm_timeout_seconds",
        mode="before",
    )
    @classmethod
    def validate_llm_timeout_value(cls, value, info):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_LLM_TIMEOUT") from None
        maximum = {
            "llm_request_timeout_seconds": 300,
            "claim_request_timeout_seconds": 600,
            "llm_workflow_timeout_seconds": 1800,
            "tutor_llm_timeout_seconds": 120,
        }[info.field_name]
        if normalized <= 0 or normalized > maximum:
            raise ValueError("CFG_INVALID_LLM_TIMEOUT")
        return value

    @field_validator(
        "llm_max_attempts",
        "claim_max_attempts",
        "llm_resource_generation_max_attempts",
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
        if info.field_name in {"llm_max_attempts", "claim_max_attempts", "llm_resource_generation_max_attempts"}:
            if not normalized.is_integer() or not 1 <= normalized <= 3:
                raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        else:
            maximum = 30 if info.field_name == "llm_retry_base_delay_seconds" else 60
            if normalized < 0 or normalized > maximum:
                raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        return value

    @field_validator(
        "llm_max_output_tokens",
        "claim_max_output_tokens",
        "llm_generator_max_output_tokens",
        "llm_resource_generator_max_input_tokens",
        "llm_resource_generator_max_output_tokens",
        "practice_guide_max_output_tokens",
        "tutor_max_output_tokens",
        mode="before",
    )
    @classmethod
    def validate_llm_token_limit(cls, value, info):
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            raise ValueError("CFG_INVALID_LLM_TOKEN_LIMIT") from None
        upper_bound = (
            262144
            if info.field_name == "llm_resource_generator_max_input_tokens"
            else 8192
            if info.field_name == "tutor_max_output_tokens"
            else 65536
        )
        lower_bound = (
            1024
            if info.field_name == "llm_resource_generator_max_input_tokens"
            else 8192
            if info.field_name in {"llm_resource_generator_max_output_tokens", "practice_guide_max_output_tokens"}
            else 256
        )
        if not normalized.is_integer() or not lower_bound <= normalized <= upper_bound:
            raise ValueError("CFG_INVALID_LLM_TOKEN_LIMIT")
        return value

    @model_validator(mode="after")
    def validate_runtime_settings(self):
        legacy_prefix = (self.chroma_collection_name or "").strip()
        if legacy_prefix and "chroma_collection_prefix" not in self.model_fields_set:
            self.chroma_collection_prefix = legacy_prefix
        if not self.chroma_collection_prefix.strip():
            self.chroma_collection_prefix = "kb"

        if self.llm_workflow_timeout_seconds <= max(
            self.llm_request_timeout_seconds,
            self.claim_request_timeout_seconds,
        ):
            raise ValueError("CFG_INVALID_LLM_TIMEOUT")
        if self.workflow_run_lease_seconds < self.llm_workflow_timeout_seconds:
            raise ValueError("CFG_INVALID_LLM_TIMEOUT")
        if self.llm_retry_max_delay_seconds < self.llm_retry_base_delay_seconds:
            raise ValueError("CFG_INVALID_LLM_RETRY_POLICY")
        if self.retrieval_min_evidence > self.retrieval_max_evidence:
            raise ValueError("CFG_INVALID_RETRIEVAL_POLICY")
        if self.workflow_sse_heartbeat_seconds <= self.workflow_sse_poll_interval_seconds:
            raise ValueError("CFG_INVALID_WORKFLOW_STREAMING_POLICY")
        if self.report_sse_heartbeat_seconds <= self.report_sse_poll_interval_seconds:
            raise ValueError("CFG_INVALID_REPORT_STREAMING_POLICY")
        if self.rerank_enabled:
            if not self.rerank_model.strip():
                raise ValueError("CFG_RERANK_MODEL_MISSING")
            if self.rerank_candidate_k <= 0 or self.rerank_per_query_k <= 0:
                raise ValueError("CFG_RERANK_CANDIDATE_INVALID")
            if self.rerank_batch_size <= 0 or self.rerank_max_length <= 0:
                raise ValueError("CFG_RERANK_RUNTIME_INVALID")
            if self.rerank_max_chunks_per_document <= 0:
                raise ValueError("CFG_RERANK_DIVERSITY_INVALID")

        stage_token_budgets = (
            self.courseware_planner_token_budget,
            self.courseware_scene_composition_token_budget,
            self.courseware_quality_review_token_budget,
            self.courseware_revision_token_budget,
        )
        if sum(stage_token_budgets) > self.courseware_total_llm_token_budget:
            raise ValueError("CFG_INVALID_COURSEWARE_STAGE_TOKEN_BUDGET")
        if self.courseware_quality_review_reserved_tokens > self.courseware_quality_review_token_budget:
            raise ValueError("CFG_INVALID_COURSEWARE_REVIEW_RESERVE")
        if self.courseware_revision_reserved_tokens > self.courseware_revision_token_budget:
            raise ValueError("CFG_INVALID_COURSEWARE_REVISION_RESERVE")
        if self.courseware_scene_call_max_tokens > 4096 or (self.courseware_scene_composition_token_budget and self.courseware_scene_call_max_tokens > self.courseware_scene_composition_token_budget):
            raise ValueError("CFG_INVALID_COURSEWARE_SCENE_CALL_LIMIT")
        stage_seconds = (
            self.courseware_planner_max_seconds,
            self.courseware_scene_composition_max_seconds,
            self.courseware_quality_review_max_seconds,
            self.courseware_revision_max_seconds,
        )
        if sum(stage_seconds) + 60 > self.courseware_total_run_timeout_seconds:
            raise ValueError("CFG_INVALID_COURSEWARE_STAGE_TIMEOUT_BUDGET")
        if self.courseware_quality_review_reserved_seconds > self.courseware_quality_review_max_seconds:
            raise ValueError("CFG_INVALID_COURSEWARE_REVIEW_TIME_RESERVE")
        if self.courseware_revision_reserved_seconds > self.courseware_revision_max_seconds:
            raise ValueError("CFG_INVALID_COURSEWARE_REVISION_TIME_RESERVE")

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
        if self.llm_proxy_url and not is_valid_http_url(self.llm_proxy_url):
            raise ValueError("CFG_LLM_PROXY_INVALID")
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
