"""Side-effect-conscious runtime readiness checks.

The checks never call a paid LLM endpoint or download an embedding model. When
``prepare_directories`` is false (the environment-check CLI), they also avoid
creating configured runtime directories.
"""

import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, Optional

from pydantic import BaseModel, Field

from app.config import (
    Settings,
    get_settings,
    is_placeholder_api_key,
    is_valid_http_url,
    resolve_backend_path,
)
from app.core.errors import ApplicationError, ErrorCode
from app.core.knowledge_base import list_knowledge_base_dirs, load_knowledge_base_manifest
from app.core.vector_store import _collection_name


class ComponentHealth(BaseModel):
    status: str
    code: Optional[str] = None
    mode: Optional[str] = None
    ephemeral: Optional[bool] = None
    collection_state: Optional[str] = None
    count: Optional[int] = None


class HealthReport(BaseModel):
    status: str
    app_mode: str
    degraded_generation_allowed: bool
    python: ComponentHealth
    storage: ComponentHealth
    llm: ComponentHealth
    embedding: ComponentHealth
    vector_store: ComponentHealth
    resources: ComponentHealth
    error_codes: list[str] = Field(default_factory=list)


class KnowledgeBaseHealth(BaseModel):
    knowledge_base_id: str
    is_default: bool = False
    status: str
    code: Optional[str] = None
    collection_name: str
    collection_state: Optional[str] = None
    count: Optional[int] = None
    index_status: Optional[str] = None
    index_schema_version: Optional[str] = None
    active_snapshot_hash: Optional[str] = None
    expected_chunk_count: Optional[int] = None
    sql_chunk_count: Optional[int] = None
    indexed_vector_chunk_count: Optional[int] = None
    smoke_status: Optional[str] = None
    last_error_code: Optional[str] = None
    last_indexed_at: Optional[datetime] = None


class KnowledgeBaseHealthReport(BaseModel):
    status: str
    default_knowledge_base_id: Optional[str] = None
    knowledge_bases: list[KnowledgeBaseHealth] = Field(default_factory=list)
    orphan_collections: list[str] = Field(default_factory=list)
    error_codes: list[str] = Field(default_factory=list)


def _failure(code: ErrorCode, *, mode: str | None = None) -> ComponentHealth:
    return ComponentHealth(status="not_ready", code=code.value, mode=mode)


def _nearest_existing_directory(path: Path) -> Optional[Path]:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if candidate.exists() and candidate.is_dir():
        return candidate
    return None


def _directory_is_writable(path: Path, prepare: bool) -> bool:
    target = path
    try:
        if prepare:
            target.mkdir(parents=True, exist_ok=True)
        elif not target.exists():
            target = _nearest_existing_directory(target)
            if target is None:
                return False
        if not target.is_dir():
            return False
        with tempfile.NamedTemporaryFile(prefix=".p0_health_", dir=target, delete=True):
            pass
        return True
    except OSError:
        return False


def _sqlite_path(database_url: str) -> Optional[Path]:
    if not database_url.startswith("sqlite:///"):
        return None
    raw_path = database_url[len("sqlite:///"):]
    if raw_path == ":memory:":
        return None
    return resolve_backend_path(raw_path)


def _check_python() -> ComponentHealth:
    if sys.version_info < (3, 11):
        return _failure(ErrorCode.CFG_UNSUPPORTED_PYTHON)
    return ComponentHealth(status="ready")


def _check_storage(settings: Settings, prepare: bool) -> ComponentHealth:
    if settings.db_type == "memory":
        return ComponentHealth(
            status="degraded",
            code=ErrorCode.STORAGE_MEMORY_EPHEMERAL.value,
            mode="memory",
            ephemeral=True,
        )

    if settings.db_type == "sqlite":
        database_path = _sqlite_path(settings.database_url)
        if database_path is None or not _directory_is_writable(database_path.parent, prepare):
            return _failure(ErrorCode.STORAGE_SQLITE_PATH_UNWRITABLE, mode="sqlite")
        return ComponentHealth(status="ready", mode="sqlite", ephemeral=False)

    return ComponentHealth(status="ready", mode="postgresql", ephemeral=False)


def _check_llm(settings: Settings) -> ComponentHealth:
    key = settings.llm_api_key.get_secret_value().strip()
    if not key:
        return _failure(ErrorCode.CFG_LLM_API_KEY_MISSING)
    if is_placeholder_api_key(key):
        return _failure(ErrorCode.CFG_LLM_API_KEY_PLACEHOLDER)
    if not is_valid_http_url(settings.llm_base_url):
        return _failure(ErrorCode.CFG_LLM_ENDPOINT_INVALID)
    if not settings.llm_model.strip():
        return _failure(ErrorCode.CFG_LLM_MODEL_MISSING)
    return ComponentHealth(status="ready")


def _check_embedding(settings: Settings) -> ComponentHealth:
    model_name = settings.embedding_model.strip()
    if not model_name:
        return _failure(ErrorCode.CFG_EMBEDDING_MODEL_MISSING)

    candidate = Path(model_name)
    if candidate.is_absolute() or model_name.startswith(("./", ".\\", "../", "..\\")):
        model_path = candidate if candidate.is_absolute() else resolve_backend_path(candidate)
        return (
            ComponentHealth(status="ready")
            if model_path.exists()
            else _failure(ErrorCode.EMBEDDING_MODEL_UNAVAILABLE)
        )

    try:
        from huggingface_hub import scan_cache_dir

        cache_info = scan_cache_dir()
        for repo in cache_info.repos:
            if repo.repo_type == "model" and repo.repo_id == model_name and repo.revisions:
                return ComponentHealth(status="ready")
    except Exception:
        pass
    return _failure(ErrorCode.EMBEDDING_MODEL_UNAVAILABLE)


def _get_chroma_client(vector_dir: Path):
    import chromadb

    return chromadb.PersistentClient(path=str(vector_dir))


def _default_knowledge_base_id(settings: Settings) -> str:
    return str(
        load_knowledge_base_manifest(settings.knowledge_base_dir)["knowledge_base_id"]
    )


def _inspect_knowledge_base_collection(
    client,
    knowledge_base_id: str,
    settings: Settings,
    *,
    is_default: bool = False,
) -> KnowledgeBaseHealth:
    collection_name = _collection_name(knowledge_base_id, settings)
    try:
        collection = client.get_collection(collection_name)
    except Exception:
        return KnowledgeBaseHealth(
            knowledge_base_id=knowledge_base_id,
            is_default=is_default,
            status="not_ready",
            code=ErrorCode.VECTOR_COLLECTION_MISSING.value,
            collection_name=collection_name,
            collection_state="missing",
        )

    if (collection.metadata or {}).get("knowledge_base_id") != knowledge_base_id:
        return KnowledgeBaseHealth(
            knowledge_base_id=knowledge_base_id,
            is_default=is_default,
            status="not_ready",
            code=ErrorCode.VECTOR_COLLECTION_METADATA_MISMATCH.value,
            collection_name=collection_name,
            collection_state="metadata_mismatch",
        )

    try:
        count = collection.count()
    except Exception:
        return KnowledgeBaseHealth(
            knowledge_base_id=knowledge_base_id,
            is_default=is_default,
            status="not_ready",
            code=ErrorCode.VECTOR_STORE_UNAVAILABLE.value,
            collection_name=collection_name,
            collection_state="unavailable",
        )

    if count == 0:
        return KnowledgeBaseHealth(
            knowledge_base_id=knowledge_base_id,
            is_default=is_default,
            status="not_ready",
            code=ErrorCode.VECTOR_COLLECTION_EMPTY.value,
            collection_name=collection_name,
            collection_state="empty",
            count=0,
        )
    return KnowledgeBaseHealth(
        knowledge_base_id=knowledge_base_id,
        is_default=is_default,
        status="ready",
        collection_name=collection_name,
        collection_state="populated",
        count=count,
    )


def _check_vector_store(
    settings: Settings,
    prepare: bool,
    *,
    index_status_provider: Callable[[str], dict | None] | None = None,
) -> ComponentHealth:
    vector_dir = resolve_backend_path(settings.vector_store_dir)
    if not _directory_is_writable(vector_dir, prepare):
        return _failure(ErrorCode.VECTOR_DIRECTORY_UNWRITABLE)

    database_file = vector_dir / "chroma.sqlite3"
    if not database_file.exists():
        return ComponentHealth(
            status="not_ready",
            code=ErrorCode.VECTOR_COLLECTION_MISSING.value,
            collection_state="missing",
        )

    try:
        client = _get_chroma_client(vector_dir)
        detail = _inspect_knowledge_base_collection(
            client,
            _default_knowledge_base_id(settings),
            settings,
            is_default=True,
        )
        component = ComponentHealth(
            status=detail.status,
            code=detail.code,
            collection_state=detail.collection_state,
            count=detail.count,
        )
        if detail.status != "ready" or index_status_provider is None:
            return component
        index = index_status_provider(detail.knowledge_base_id)
        if not index:
            return component
        live_sql_count = index.get(
            "live_sql_active_chunk_count",
            index.get("sql_chunk_count"),
        )
        if (
            index.get("status") != "ready"
            or index.get("smoke_status") == "failed"
            or index.get("expected_chunk_count") != live_sql_count
            or live_sql_count != detail.count
        ):
            return _failure(
                ErrorCode(
                    index.get("last_error_code")
                    or (
                        ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED.value
                        if index.get("smoke_status") == "failed"
                        else ErrorCode.VECTOR_INDEX_OUT_OF_SYNC.value
                    )
                )
            )
        return component
    except Exception:
        return _failure(ErrorCode.VECTOR_STORE_UNAVAILABLE)


def _check_resources(settings: Settings, prepare: bool) -> ComponentHealth:
    resources_dir = resolve_backend_path(settings.resources_dir)
    if not _directory_is_writable(resources_dir, prepare):
        return _failure(ErrorCode.RESOURCE_DIRECTORY_UNWRITABLE)
    return ComponentHealth(status="ready")


def _aggregate_status(settings: Settings, components: Dict[str, ComponentHealth]) -> str:
    hard_failure = (
        components["python"].status == "not_ready"
        or components["resources"].status == "not_ready"
        or (
            components["storage"].status == "not_ready"
            and components["storage"].code != ErrorCode.STORAGE_MEMORY_EPHEMERAL.value
        )
        or components["vector_store"].code == ErrorCode.VECTOR_DIRECTORY_UNWRITABLE.value
    )
    if hard_failure:
        return "not_ready"

    has_issue = any(component.status != "ready" for component in components.values())
    if not has_issue:
        return "ready"
    if settings.app_mode != "production" and settings.allow_degraded_generation:
        return "degraded"
    return "not_ready"


def build_health_report(
    settings: Settings | None = None,
    *,
    prepare_directories: bool = False,
    overrides: Dict[str, ErrorCode] | None = None,
    index_status_provider: Callable[[str], dict | None] | None = None,
) -> HealthReport:
    settings = settings or get_settings()
    components = {
        "python": _check_python(),
        "storage": _check_storage(settings, prepare_directories),
        "llm": _check_llm(settings),
        "embedding": _check_embedding(settings),
        "vector_store": (
            _check_vector_store(
                settings,
                prepare_directories,
                index_status_provider=index_status_provider,
            )
            if index_status_provider is not None
            else _check_vector_store(settings, prepare_directories)
        ),
        "resources": _check_resources(settings, prepare_directories),
    }
    for component_name, code in (overrides or {}).items():
        if component_name in components:
            mode = settings.db_type if component_name == "storage" else None
            components[component_name] = _failure(code, mode=mode)

    status = _aggregate_status(settings, components)
    error_codes = list(dict.fromkeys(
        component.code for component in components.values() if component.code
    ))
    return HealthReport(
        status=status,
        app_mode=settings.app_mode,
        degraded_generation_allowed=(
            settings.allow_degraded_generation and settings.app_mode != "production"
        ),
        error_codes=error_codes,
        **components,
    )


def ensure_generation_ready(
    settings: Settings | None = None,
    *,
    index_status_provider: Callable[[str], dict | None] | None = None,
) -> HealthReport:
    report = build_health_report(
        settings,
        index_status_provider=index_status_provider,
    )
    if report.status == "not_ready":
        raise ApplicationError(ErrorCode.GENERATION_DEPENDENCY_UNAVAILABLE)
    return report


def build_knowledge_base_health_report(
    settings: Settings | None = None,
    *,
    index_status_provider: Callable[[str], dict | None] | None = None,
) -> KnowledgeBaseHealthReport:
    """Inspect every configured KB for administrators without loading embeddings.

    The public readiness report intentionally does not call this function. A
    non-default KB failure therefore cannot turn the whole service into HTTP
    503; it is represented as a degraded administrator report instead.
    """
    settings = settings or get_settings()
    try:
        default_id = _default_knowledge_base_id(settings)
    except Exception:
        return KnowledgeBaseHealthReport(
            status="not_ready",
            error_codes=[ErrorCode.KNOWLEDGE_BASE_MANIFEST_INVALID.value],
        )

    configured: list[tuple[str, Optional[str]]] = []
    for directory in list_knowledge_base_dirs():
        try:
            knowledge_base_id = str(
                load_knowledge_base_manifest(str(directory))["knowledge_base_id"]
            )
            configured.append((knowledge_base_id, None))
        except Exception:
            configured.append((directory.name, ErrorCode.KNOWLEDGE_BASE_MANIFEST_INVALID.value))
    if default_id not in {knowledge_base_id for knowledge_base_id, _ in configured}:
        configured.insert(0, (default_id, None))

    vector_dir = resolve_backend_path(settings.vector_store_dir)
    database_file = vector_dir / "chroma.sqlite3"
    if not vector_dir.is_dir() or not database_file.exists():
        details = [
            KnowledgeBaseHealth(
                knowledge_base_id=knowledge_base_id,
                is_default=knowledge_base_id == default_id,
                status="not_ready",
                code=manifest_error or ErrorCode.VECTOR_COLLECTION_MISSING.value,
                collection_name=_collection_name(knowledge_base_id, settings),
                collection_state="manifest_invalid" if manifest_error else "missing",
            )
            for knowledge_base_id, manifest_error in configured
        ]
        return KnowledgeBaseHealthReport(
            status="not_ready",
            default_knowledge_base_id=default_id,
            knowledge_bases=details,
            error_codes=list(dict.fromkeys(item.code for item in details if item.code)),
        )

    try:
        client = _get_chroma_client(vector_dir)
        collections = {collection.name for collection in client.list_collections()}
    except Exception:
        return KnowledgeBaseHealthReport(
            status="not_ready",
            default_knowledge_base_id=default_id,
            error_codes=[ErrorCode.VECTOR_STORE_UNAVAILABLE.value],
        )

    details = []
    for knowledge_base_id, manifest_error in configured:
        if manifest_error:
            details.append(
                KnowledgeBaseHealth(
                    knowledge_base_id=knowledge_base_id,
                    is_default=knowledge_base_id == default_id,
                    status="not_ready",
                    code=manifest_error,
                    collection_name=_collection_name(knowledge_base_id, settings),
                    collection_state="manifest_invalid",
                )
            )
            continue
        details.append(
            _inspect_knowledge_base_collection(
                client,
                knowledge_base_id,
                settings,
                is_default=knowledge_base_id == default_id,
            )
        )

    if index_status_provider is not None:
        enriched: list[KnowledgeBaseHealth] = []
        for item in details:
            try:
                index = index_status_provider(item.knowledge_base_id)
            except Exception:
                index = None
            if not index:
                enriched.append(item)
                continue
            live_sql_count = index.get(
                "live_sql_active_chunk_count",
                index.get("sql_chunk_count"),
            )
            expected_count = index.get("expected_chunk_count")
            counts_match = (
                item.count is not None
                and expected_count == live_sql_count == item.count
            )
            index_ready = (
                index.get("status") == "ready"
                and index.get("smoke_status") != "failed"
                and counts_match
            )
            code = item.code
            if not index_ready:
                code = (
                    index.get("last_error_code")
                    or (
                        ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED.value
                        if index.get("smoke_status") == "failed"
                        else ErrorCode.VECTOR_INDEX_OUT_OF_SYNC.value
                    )
                )
            enriched.append(item.model_copy(update={
                "status": item.status if index_ready else "not_ready",
                "code": code,
                "index_status": index.get("status"),
                "index_schema_version": index.get("index_schema_version"),
                "active_snapshot_hash": index.get("active_snapshot_hash"),
                "expected_chunk_count": expected_count,
                "sql_chunk_count": live_sql_count,
                "indexed_vector_chunk_count": index.get("vector_chunk_count"),
                "smoke_status": index.get("smoke_status"),
                "last_error_code": index.get("last_error_code"),
                "last_indexed_at": index.get("last_indexed_at"),
            }))
        details = enriched

    expected_names = {item.collection_name for item in details}
    default_health = next((item for item in details if item.is_default), None)
    if default_health is None or default_health.status != "ready":
        status = "not_ready"
    elif any(item.status != "ready" for item in details):
        status = "degraded"
    else:
        status = "ready"
    return KnowledgeBaseHealthReport(
        status=status,
        default_knowledge_base_id=default_id,
        knowledge_bases=details,
        orphan_collections=sorted(collections - expected_names),
        error_codes=list(dict.fromkeys(item.code for item in details if item.code)),
    )
