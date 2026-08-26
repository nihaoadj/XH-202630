"""Idempotent SQL/vector reconciliation for one versioned knowledge base."""

from __future__ import annotations

import logging
from typing import Protocol

from langchain.schema import Document

from app.core.security.errors import ErrorCode, PUBLIC_MESSAGES
from app.core.retrieval.knowledge_base import (
    DEFAULT_CHUNKING_STRATEGY,
    chunk_documents,
    load_documents,
    load_knowledge_base_manifest,
    resolve_knowledge_base_dir_by_id,
)
from app.core.retrieval.knowledge_ids import canonical_json, query_hash, sha256_hex
from app.core.retrieval.vector_store import (
    ChromaVectorSearchBackend,
    synchronize_documents,
    vector_store_count,
)
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.shared.common import ErrorInfo
from app.models.knowledge.knowledge import (
    IngestionReport,
    IngestionSmokeResult,
    VectorCandidate,
)


logger = logging.getLogger(__name__)


class KnowledgeVectorIndex(Protocol):
    def synchronize(
        self,
        documents: list[Document],
        *,
        knowledge_base_id: str,
    ) -> list[str]: ...

    def count(self, knowledge_base_id: str) -> int: ...

    def search(
        self,
        *,
        query: str,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]: ...


class ChromaKnowledgeVectorIndex:
    def __init__(self, search_backend: ChromaVectorSearchBackend | None = None):
        self.search_backend = search_backend or ChromaVectorSearchBackend()

    def synchronize(
        self,
        documents: list[Document],
        *,
        knowledge_base_id: str,
    ) -> list[str]:
        return synchronize_documents(
            documents,
            knowledge_base_id=knowledge_base_id,
        )

    def count(self, knowledge_base_id: str) -> int:
        return vector_store_count(knowledge_base_id)

    def search(
        self,
        *,
        query: str,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]:
        return self.search_backend.search(
            query=query,
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )


class _IngestionFailure(Exception):
    def __init__(self, code: ErrorCode, safe_detail: str):
        self.code = code
        self.safe_detail = safe_detail
        super().__init__(code.value)


def _error(failure: _IngestionFailure) -> ErrorInfo:
    return ErrorInfo(
        code=failure.code.value,
        category="ingestion",
        message=PUBLIC_MESSAGES.get(failure.code, "知识库入库失败"),
        retryable=failure.code == ErrorCode.KNOWLEDGE_INGESTION_FAILED,
        source="ingestion_service",
        safe_detail=failure.safe_detail,
    )


class IngestionService:
    def __init__(
        self,
        *,
        catalog: KnowledgeCatalogRepository,
        vector_index: KnowledgeVectorIndex,
    ):
        self.catalog = catalog
        self.vector_index = vector_index

    def reconcile(self, knowledge_base_id: str) -> IngestionReport:
        """Explicitly rebuild one configured KB from its authoritative files.

        ``ingest`` is already snapshot-based and idempotent, so reconciliation
        intentionally performs a complete re-ingest. This repairs every crash
        window (before/after SQL staging, Chroma replacement, smoke checks, or
        SQL activation) without trying to infer which partial side is newer.
        """
        knowledge_base_dir = resolve_knowledge_base_dir_by_id(knowledge_base_id)
        return self.ingest(str(knowledge_base_dir))

    @staticmethod
    def _validate_snapshot(
        knowledge_base_id: str,
        documents: list[Document],
        chunks: list[Document],
    ) -> None:
        if not documents or not chunks:
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:empty",
            )
        document_ids = [str(item.metadata.get("document_id") or "") for item in documents]
        versions = [str(item.metadata.get("document_version") or "") for item in documents]
        chunk_ids = [str(item.metadata.get("chunk_id") or "") for item in chunks]
        if any(not value for value in document_ids + versions + chunk_ids):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:identity_missing",
            )
        if len(document_ids) != len(set(document_ids)):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:document_id_duplicate",
            )
        if len(versions) != len(set(versions)):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:document_version_duplicate",
            )
        if len(chunk_ids) != len(set(chunk_ids)):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:chunk_id_duplicate",
            )
        if any(
            item.metadata.get("knowledge_base_id") != knowledge_base_id
            for item in documents + chunks
        ):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                "snapshot:knowledge_base_mismatch",
            )

    def _smoke(
        self,
        *,
        knowledge_base_id: str,
        specs: object,
    ) -> tuple[str, list[IngestionSmokeResult]]:
        if not specs:
            return "not_configured", []
        if not isinstance(specs, list):
            raise _IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED,
                "manifest:smoke_queries_invalid",
            )
        results: list[IngestionSmokeResult] = []
        for spec in specs:
            if not isinstance(spec, dict):
                raise _IngestionFailure(
                    ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED,
                    "manifest:smoke_query_invalid",
                )
            query = str(spec.get("query") or "").strip()
            expected_docs = [str(item) for item in spec.get("expected_document_ids", [])]
            expected_chunks = [str(item) for item in spec.get("expected_chunk_ids", [])]
            if not query or not (expected_docs or expected_chunks):
                raise _IngestionFailure(
                    ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED,
                    "manifest:smoke_expectation_missing",
                )
            candidates = self.vector_index.search(
                query=query,
                top_k=max(5, len(expected_docs) + len(expected_chunks)),
                knowledge_base_id=knowledge_base_id,
            )
            hit_docs = list(dict.fromkeys(
                str(item.metadata.get("document_id") or "") for item in candidates
            ))
            hit_chunks = list(dict.fromkeys(item.chunk_id for item in candidates))
            passed = (
                (not expected_docs or bool(set(expected_docs) & set(hit_docs)))
                and (not expected_chunks or bool(set(expected_chunks) & set(hit_chunks)))
            )
            results.append(IngestionSmokeResult(
                query_hash=query_hash(query),
                expected_document_ids=expected_docs,
                expected_chunk_ids=expected_chunks,
                hit_document_ids=hit_docs,
                hit_chunk_ids=hit_chunks,
                passed=passed,
            ))
        return (
            "passed" if all(item.passed for item in results) else "failed",
            results,
        )

    def ingest(self, knowledge_base_dir: str | None = None) -> IngestionReport:
        manifest = load_knowledge_base_manifest(knowledge_base_dir)
        knowledge_base_id = str(manifest.get("knowledge_base_id") or "").strip()
        index_schema_version = str(manifest.get("index_schema_version") or "1.0")
        if not knowledge_base_id:
            raise ValueError("knowledge_base_id is required")

        documents: list[Document] = []
        chunks: list[Document] = []
        snapshot_hash: str | None = None
        smoke_status = "not_run"
        smoke_results: list[IngestionSmokeResult] = []
        sql_count = 0
        vector_count = 0
        stage = "snapshot_load"
        try:
            chunking = manifest.get("chunking") or {}
            strategy = str(chunking.get("strategy") or DEFAULT_CHUNKING_STRATEGY)
            if strategy not in {DEFAULT_CHUNKING_STRATEGY, "recursive_v1"}:
                raise _IngestionFailure(
                    ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                    "manifest:chunking_strategy_unsupported",
                )
            chunk_size = int(chunking.get("chunk_size", 500))
            chunk_overlap = int(chunking.get("chunk_overlap", 100))
            documents = load_documents(knowledge_base_dir)
            chunks = chunk_documents(
                documents,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
            )
            self._validate_snapshot(knowledge_base_id, documents, chunks)
            snapshot_hash = sha256_hex(canonical_json({
                "knowledge_base_id": knowledge_base_id,
                "index_schema_version": index_schema_version,
                "document_versions": sorted(
                    item.metadata["document_version"] for item in documents
                ),
                "chunk_ids": sorted(item.metadata["chunk_id"] for item in chunks),
            }))
            stage = "sql_staging"
            self.catalog.upsert_knowledge_base(manifest)
            self.catalog.set_index_status(
                knowledge_base_id,
                status="indexing",
                index_schema_version=index_schema_version,
                active_snapshot_hash=snapshot_hash,
                expected_chunk_count=len(chunks),
                smoke_status="not_run",
            )
            self.catalog.sync_documents(
                documents,
                chunks,
                knowledge_base_id=knowledge_base_id,
                activate=False,
            )
            stage = "vector_synchronize"
            self.vector_index.synchronize(
                chunks,
                knowledge_base_id=knowledge_base_id,
            )
            stage = "vector_count"
            vector_count = self.vector_index.count(knowledge_base_id)
            if len(chunks) != vector_count:
                raise _IngestionFailure(
                    ErrorCode.VECTOR_INDEX_OUT_OF_SYNC,
                    "counts:mismatch",
                )
            stage = "smoke_queries"
            smoke_status, smoke_results = self._smoke(
                knowledge_base_id=knowledge_base_id,
                specs=manifest.get("smoke_queries"),
            )
            if smoke_status == "failed":
                raise _IngestionFailure(
                    ErrorCode.KNOWLEDGE_INGESTION_SMOKE_FAILED,
                    "smoke:expectation_not_met",
                )
            stage = "sql_activation"
            self.catalog.activate_snapshot(
                knowledge_base_id,
                document_versions=[
                    item.metadata["document_version"] for item in documents
                ],
                chunk_ids=[item.metadata["chunk_id"] for item in chunks],
            )
            stage = "count_reconciliation"
            sql_count = self.catalog.active_chunk_count(knowledge_base_id)
            if len(chunks) != sql_count or sql_count != vector_count:
                raise _IngestionFailure(
                    ErrorCode.VECTOR_INDEX_OUT_OF_SYNC,
                    "counts:mismatch",
                )
        except _IngestionFailure as failure:
            error = _error(failure)
        except Exception as exc:
            logger.error(
                "Knowledge ingestion failed knowledge_base_id=%s stage=%s exception_type=%s",
                knowledge_base_id,
                stage,
                type(exc).__name__,
            )
            error = _error(_IngestionFailure(
                ErrorCode.KNOWLEDGE_INGESTION_FAILED,
                f"{stage}:failed",
            ))
        else:
            self.catalog.set_index_status(
                knowledge_base_id,
                status="ready",
                index_schema_version=index_schema_version,
                active_snapshot_hash=snapshot_hash,
                expected_chunk_count=len(chunks),
                sql_chunk_count=sql_count,
                vector_chunk_count=vector_count,
                smoke_status=smoke_status,
            )
            return IngestionReport(
                knowledge_base_id=knowledge_base_id,
                status="ready",
                index_schema_version=index_schema_version,
                active_snapshot_hash=snapshot_hash,
                document_count=len(documents),
                expected_active_chunk_count=len(chunks),
                sql_active_chunk_count=sql_count,
                vector_chunk_count=vector_count,
                smoke_status=smoke_status,
                smoke_results=smoke_results,
            )

        # A failed reconciliation remains diagnosable and idempotently retryable.
        try:
            sql_count = self.catalog.active_chunk_count(knowledge_base_id)
            vector_count = self.vector_index.count(knowledge_base_id)
        except Exception:
            pass
        self.catalog.set_index_status(
            knowledge_base_id,
            status="not_ready",
            index_schema_version=index_schema_version,
            active_snapshot_hash=snapshot_hash,
            expected_chunk_count=len(chunks),
            sql_chunk_count=sql_count,
            vector_chunk_count=vector_count,
            smoke_status=smoke_status,
            last_error_code=error.code,
        )
        return IngestionReport(
            knowledge_base_id=knowledge_base_id,
            status="not_ready",
            index_schema_version=index_schema_version,
            active_snapshot_hash=snapshot_hash,
            document_count=len(documents),
            expected_active_chunk_count=len(chunks),
            sql_active_chunk_count=sql_count,
            vector_chunk_count=vector_count,
            smoke_status=smoke_status,
            smoke_results=smoke_results,
            error=error,
        )
