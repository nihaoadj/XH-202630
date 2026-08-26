"""Validated, KB-scoped conversion from vector candidates to Evidence DTOs."""

from __future__ import annotations

import logging
from time import perf_counter
from datetime import datetime, timezone
from functools import lru_cache
from typing import Callable, Protocol

from app.config import Settings, get_settings
from app.core.security.errors import ErrorCode, PUBLIC_MESSAGES
from app.core.retrieval.knowledge_ids import (
    evidence_id,
    normalize_text,
    query_hash,
    retrieval_config_hash,
    sha256_hex,
)
from app.core.retrieval.vector_store import ChromaVectorSearchBackend
from app.db.shared.database import get_session_factory
from app.db.knowledge.base import KnowledgeChunkRepository
from app.db.knowledge.catalog import KnowledgeCatalogRepository
from app.models.shared.common import ErrorInfo
from app.models.knowledge.knowledge import (
    EvidenceBatch,
    EvidenceItem,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalStatus,
    ScoreKind,
    VectorCandidate,
)


logger = logging.getLogger(__name__)


class VectorSearchBackend(Protocol):
    def search(
        self,
        *,
        query: str,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]: ...


class _EvidenceFailure(Exception):
    def __init__(
        self,
        code: ErrorCode,
        *,
        category: str,
        retryable: bool = False,
        safe_detail: str | None = None,
    ):
        self.code = code
        self.category = category
        self.retryable = retryable
        self.safe_detail = safe_detail
        super().__init__(code.value)


def retrieval_policy_from_settings(
    settings: Settings,
    *,
    top_k_override: int | None = None,
) -> RetrievalPolicy:
    return RetrievalPolicy(
        top_k_per_query=top_k_override or settings.retrieval_top_k_default,
        max_query_count=settings.retrieval_max_queries,
        min_normalized_score=settings.retrieval_min_normalized_score,
        min_evidence_count=settings.retrieval_min_evidence,
        max_evidence_count=settings.retrieval_max_evidence,
        max_excerpt_chars=settings.evidence_max_excerpt_chars,
        distance_metric=settings.vector_distance_metric,
    )


def _config_payload(settings: Settings, policy: RetrievalPolicy) -> dict:
    return {
        "schema_version": "1.0",
        "collection_resolver_version": "kb-hash-v1",
        "embedding_model": settings.embedding_model,
        **policy.model_dump(mode="json"),
    }


def _error_info(failure: _EvidenceFailure) -> ErrorInfo:
    return ErrorInfo(
        code=failure.code.value,
        category=failure.category,
        message=PUBLIC_MESSAGES.get(failure.code, "知识检索失败"),
        retryable=failure.retryable,
        source="evidence_retriever",
        safe_detail=failure.safe_detail,
    )


class EvidenceRetriever:
    def __init__(
        self,
        *,
        backend: VectorSearchBackend,
        chunk_repository: KnowledgeChunkRepository,
        settings: Settings | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self.backend = backend
        self.chunk_repository = chunk_repository
        self.settings = settings or get_settings()
        self.clock = clock

    @staticmethod
    def _normalize_score(candidate: VectorCandidate) -> float:
        metric = candidate.metric.lower()
        if metric != "cosine":
            raise _EvidenceFailure(
                ErrorCode.RETRIEVAL_SCORE_UNSUPPORTED,
                category="retrieval",
                safe_detail="metric:unsupported",
            )
        if candidate.score_kind == ScoreKind.DISTANCE:
            value = 1.0 - candidate.raw_score / 2.0
        elif candidate.score_kind == ScoreKind.SIMILARITY:
            value = (candidate.raw_score + 1.0) / 2.0
        else:  # pragma: no cover - enum validation prevents this branch
            raise _EvidenceFailure(
                ErrorCode.RETRIEVAL_SCORE_UNSUPPORTED,
                category="retrieval",
            )
        return max(0.0, min(1.0, value))

    def _validate_candidate(
        self,
        candidate: VectorCandidate,
        request: RetrievalRequest,
    ):
        metadata = candidate.metadata
        if (
            candidate.query not in request.queries
            or candidate.query_rank > request.policy.top_k_per_query
        ):
            raise _EvidenceFailure(
                ErrorCode.RETRIEVAL_QUERY_INVALID,
                category="retrieval",
                safe_detail="candidate_query:out_of_contract",
            )
        candidate_kb = str(metadata.get("knowledge_base_id") or "")
        if candidate_kb != request.knowledge_base_id:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_SCOPE_VIOLATION,
                category="evidence",
                safe_detail="knowledge_base_id:mismatch",
            )
        metadata_chunk_id = str(metadata.get("chunk_id") or "")
        if metadata_chunk_id != candidate.chunk_id:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="chunk_id:mismatch",
            )
        document_id = str(metadata.get("document_id") or "")
        document_version = str(metadata.get("document_version") or "")
        if not document_id or not document_version:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="document_identity:missing",
            )

        chunk = self.chunk_repository.get_chunk(
            candidate.chunk_id,
            knowledge_base_id=request.knowledge_base_id,
            document_version=document_version,
        )
        if chunk is None or chunk.document_id != document_id:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="chunk:unresolvable",
            )
        if not self.chunk_repository.is_chunk_active(
            request.knowledge_base_id,
            candidate.chunk_id,
        ):
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="chunk:inactive",
            )
        candidate_hash = str(
            metadata.get("text_hash") or metadata.get("content_hash") or ""
        )
        if candidate_hash != chunk.text_hash:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="text_hash:mismatch",
            )
        if sha256_hex(normalize_text(candidate.text)) != chunk.text_hash:
            raise _EvidenceFailure(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                category="evidence",
                safe_detail="content:mismatch",
            )
        return chunk

    def _failed_batch(
        self,
        *,
        request: RetrievalRequest,
        config_hash: str,
        query_hashes: list[str],
        candidate_count: int,
        partial_failure_count: int,
        failure: _EvidenceFailure,
        status: RetrievalStatus = RetrievalStatus.RETRIEVAL_ERROR,
        retrieval_profile: dict[str, object] | None = None,
    ) -> EvidenceBatch:
        logger.warning(
            "Evidence retrieval failed run_id=%s step_id=%s kb_id=%s code=%s candidates=%s",
            request.run_id,
            request.step_id,
            request.knowledge_base_id,
            failure.code.value,
            candidate_count,
        )
        return EvidenceBatch(
            status=status,
            knowledge_base_id=request.knowledge_base_id,
            evidence=[],
            query_hashes=query_hashes,
            query_count=len(query_hashes),
            candidate_count=candidate_count,
            dropped_candidate_count=candidate_count,
            partial_failure_count=partial_failure_count,
            config_hash=config_hash,
            retrieval_profile=retrieval_profile or {},
            error=_error_info(failure),
        )

    def retrieve(self, request: RetrievalRequest) -> EvidenceBatch:
        retrieval_started = perf_counter()
        policy = request.policy
        queries = request.queries[: policy.max_query_count]
        query_hashes = [query_hash(query) for query in queries]
        config_hash = retrieval_config_hash(
            _config_payload(self.settings, policy)
        )
        candidates: list[VectorCandidate] = []
        partial_failures = 0
        query_profiles: list[dict[str, object]] = []

        search_many = getattr(self.backend, "search_many", None)
        if callable(search_many):
            try:
                candidates.extend(search_many(
                    queries=queries,
                    top_k=policy.top_k_per_query,
                    knowledge_base_id=request.knowledge_base_id,
                ))
                backend_profile = getattr(self.backend, "last_profile", None)
                if isinstance(backend_profile, dict):
                    query_profiles = [
                        dict(item)
                        for item in backend_profile.get("query_profiles", [])
                        if isinstance(item, dict)
                    ]
                    partial_failures = int(backend_profile.get("partial_failure_count", 0))
            except Exception:
                partial_failures = len(queries)
        else:
            for query in queries:
                try:
                    candidates.extend(self.backend.search(
                        query=query,
                        top_k=policy.top_k_per_query,
                        knowledge_base_id=request.knowledge_base_id,
                    ))
                    backend_profile = getattr(self.backend, "last_profile", None)
                    if isinstance(backend_profile, dict):
                        query_profiles.append(dict(backend_profile))
                except Exception:
                    partial_failures += 1

        retrieval_profile = {
            "query_count": len(queries),
            "query_profiles": query_profiles,
            "total_retrieval_ms": round((perf_counter() - retrieval_started) * 1000, 3),
        }
        backend_profile = getattr(self.backend, "last_profile", None)
        if isinstance(backend_profile, dict) and callable(search_many):
            retrieval_profile.update(backend_profile)

        if not candidates:
            if partial_failures:
                return self._failed_batch(
                    request=request,
                    config_hash=config_hash,
                    query_hashes=query_hashes,
                    candidate_count=0,
                    partial_failure_count=partial_failures,
                    failure=_EvidenceFailure(
                        ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE,
                        category="retrieval",
                        retryable=True,
                    ),
                    retrieval_profile=retrieval_profile,
                )
            return EvidenceBatch(
                status=RetrievalStatus.NO_HIT,
                knowledge_base_id=request.knowledge_base_id,
                evidence=[],
                query_hashes=query_hashes,
                query_count=len(queries),
                candidate_count=0,
                dropped_candidate_count=0,
                config_hash=config_hash,
                retrieval_profile=retrieval_profile,
            )

        query_order = {query: index for index, query in enumerate(queries)}
        validated: dict[str, tuple[VectorCandidate, object, float]] = {}
        # Preserve node-query provenance before the global chunk dedupe below.
        # A chunk can support several nodes even though the immutable evidence
        # snapshot stores it only once.
        node_validated: dict[str, dict[str, tuple[VectorCandidate, object, float]]] = {}
        try:
            for candidate in candidates:
                chunk = self._validate_candidate(candidate, request)
                normalized_score = self._normalize_score(candidate)
                if normalized_score < policy.min_normalized_score:
                    continue
                node_id = request.query_node_ids.get(candidate.query)
                if node_id:
                    per_node = node_validated.setdefault(node_id, {})
                    node_previous = per_node.get(candidate.chunk_id)
                    node_key = (normalized_score, -candidate.query_rank)
                    node_previous_key = (
                        (node_previous[2], -node_previous[0].query_rank)
                        if node_previous is not None else None
                    )
                    if node_previous_key is None or node_key > node_previous_key:
                        per_node[candidate.chunk_id] = (candidate, chunk, normalized_score)
                previous = validated.get(candidate.chunk_id)
                key = (
                    normalized_score,
                    -query_order.get(candidate.query, len(queries)),
                    -candidate.query_rank,
                )
                previous_key = None
                if previous is not None:
                    previous_key = (
                        previous[2],
                        -query_order.get(previous[0].query, len(queries)),
                        -previous[0].query_rank,
                    )
                if previous_key is None or key > previous_key:
                    validated[candidate.chunk_id] = (
                        candidate,
                        chunk,
                        normalized_score,
                    )
        except _EvidenceFailure as failure:
            return self._failed_batch(
                request=request,
                config_hash=config_hash,
                query_hashes=query_hashes,
                candidate_count=len(candidates),
                partial_failure_count=partial_failures,
                failure=failure,
                retrieval_profile=retrieval_profile,
            )

        globally_ranked = sorted(
            validated.values(),
            key=lambda item: (
                -item[2],
                query_order.get(item[0].query, len(queries)),
                item[0].query_rank,
                item[0].chunk_id,
            ),
        )
        # Reserve the strongest valid chunk for every targeted node before
        # filling the remaining global budget.  This prevents one broad topic
        # query from starving a selected node while retaining one total pool.
        selected_chunk_ids: list[str] = []
        node_order = list(dict.fromkeys(request.query_node_ids.values()))
        for node_id in node_order:
            candidates_for_node = sorted(
                node_validated.get(node_id, {}).values(),
                key=lambda item: (-item[2], item[0].query_rank, item[0].chunk_id),
            )
            if candidates_for_node:
                selected_chunk_ids.append(candidates_for_node[0][0].chunk_id)
        selected_chunk_ids = list(dict.fromkeys(selected_chunk_ids))[: policy.max_evidence_count]
        for candidate, _chunk, _score in globally_ranked:
            if len(selected_chunk_ids) >= policy.max_evidence_count:
                break
            if candidate.chunk_id not in selected_chunk_ids:
                selected_chunk_ids.append(candidate.chunk_id)
        selected_chunk_set = set(selected_chunk_ids)
        ranked = [item for item in globally_ranked if item[0].chunk_id in selected_chunk_set]
        if len(ranked) < policy.min_evidence_count:
            if partial_failures:
                return self._failed_batch(
                    request=request,
                    config_hash=config_hash,
                    query_hashes=query_hashes,
                    candidate_count=len(candidates),
                    partial_failure_count=partial_failures,
                    failure=_EvidenceFailure(
                        ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE,
                        category="retrieval",
                        retryable=True,
                        safe_detail="queries:partial_failure_insufficient",
                    ),
                    retrieval_profile=retrieval_profile,
                )
            return self._failed_batch(
                request=request,
                config_hash=config_hash,
                query_hashes=query_hashes,
                candidate_count=len(candidates),
                partial_failure_count=partial_failures,
                failure=_EvidenceFailure(
                    ErrorCode.EVIDENCE_INSUFFICIENT,
                    category="evidence",
                    safe_detail="policy:min_evidence_count",
                ),
                status=RetrievalStatus.EVIDENCE_INSUFFICIENT,
                retrieval_profile=retrieval_profile,
            )

        retrieved_at = self.clock()
        evidence: list[EvidenceItem] = []
        evidence_by_chunk: dict[str, str] = {}
        for rank, (candidate, chunk, normalized_score) in enumerate(ranked, start=1):
            hashed_query = query_hash(candidate.query)
            excerpt = normalize_text(chunk.text)[: policy.max_excerpt_chars]
            item = EvidenceItem(
                evidence_id=evidence_id(
                    run_id=request.run_id,
                    step_id=request.step_id,
                    knowledge_base_id=request.knowledge_base_id,
                    retrieval_query_hash=hashed_query,
                    knowledge_chunk_id=chunk.chunk_id,
                    config_hash=config_hash,
                ),
                knowledge_base_id=chunk.knowledge_base_id,
                document_id=chunk.document_id,
                document_version=chunk.document_version,
                chunk_id=chunk.chunk_id,
                query=candidate.query,
                query_hash=hashed_query,
                query_rank=candidate.query_rank,
                rank=rank,
                raw_score=candidate.raw_score,
                score_kind=candidate.score_kind,
                normalized_score=normalized_score,
                excerpt=excerpt,
                excerpt_hash=sha256_hex(excerpt),
                locator=chunk.locator,
                config_hash=config_hash,
                retrieved_at=retrieved_at,
            )
            evidence.append(item)
            evidence_by_chunk[chunk.chunk_id] = item.evidence_id
        node_evidence_map: dict[str, list[str]] = {}
        for node_id in node_order:
            ordered = sorted(
                node_validated.get(node_id, {}).values(),
                key=lambda item: (-item[2], item[0].query_rank, item[0].chunk_id),
            )
            ids = [evidence_by_chunk[item[0].chunk_id] for item in ordered
                   if item[0].chunk_id in evidence_by_chunk]
            if ids:
                node_evidence_map[node_id] = list(dict.fromkeys(ids))
        return EvidenceBatch(
            status=RetrievalStatus.AVAILABLE,
            knowledge_base_id=request.knowledge_base_id,
            evidence=evidence,
            node_evidence_map=node_evidence_map,
            query_hashes=query_hashes,
            query_count=len(queries),
            candidate_count=len(candidates),
            dropped_candidate_count=max(0, len(candidates) - len(evidence)),
            partial_failure_count=partial_failures,
            config_hash=config_hash,
            retrieval_profile={
                **retrieval_profile,
                "total_retrieval_ms": round((perf_counter() - retrieval_started) * 1000, 3),
                "unique_candidate_count": len(validated),
                "final_evidence_count": len(evidence),
                "node_evidence_counts": {key: len(value) for key, value in node_evidence_map.items()},
                "unmapped_node_count": sum(1 for node_id in node_order if node_id not in node_evidence_map),
            },
        )


@lru_cache()
def default_evidence_retriever() -> EvidenceRetriever:
    settings = get_settings()
    # Keep workflow construction side-effect free. The engine/session is opened
    # only when a candidate actually needs SQL provenance resolution.
    repository = KnowledgeCatalogRepository(lambda: get_session_factory()())
    return EvidenceRetriever(
        backend=ChromaVectorSearchBackend(settings),
        chunk_repository=repository,
        settings=settings,
    )
