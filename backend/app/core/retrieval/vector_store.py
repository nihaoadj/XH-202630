"""按知识库隔离的 Chroma 向量存储访问层。"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import json
import math
import os
import re
import logging
from time import perf_counter
from typing import Iterable, Optional

from langchain_community.vectorstores import Chroma
from langchain.schema import Document

from app.config import Settings, get_settings, resolve_backend_path
from app.core.retrieval.embeddings import get_embeddings
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.models.knowledge.knowledge import ScoreKind, VectorCandidate


logger = logging.getLogger(__name__)

def _collection_name(knowledge_base_id: str, settings: Settings | None = None) -> str:
    """Return the one canonical Chroma collection name for a knowledge base.

    ``CHROMA_COLLECTION_NAME`` is retained for one compatibility window, but is
    interpreted by ``Settings`` as a prefix. It is never used as one global
    collection name shared by multiple knowledge bases.
    """
    settings = settings or get_settings()
    prefix = re.sub(r"[^a-zA-Z0-9_-]+", "_", settings.chroma_collection_prefix.strip())
    prefix = prefix.strip("_-")[:32] or "kb"
    digest = hashlib.sha256(knowledge_base_id.encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{digest}"


def _resolve_knowledge_base_id(knowledge_base_id: Optional[str]) -> str:
    if knowledge_base_id:
        return knowledge_base_id
    return str(load_knowledge_base_manifest()["knowledge_base_id"])


# Chroma metadata accepts scalar values only.  The source document metadata also
# deliberately carries lists (knowledge points, learner levels and source URLs),
# so encode those values at the storage boundary instead of throwing away
# provenance needed by retrieval and audit features.
_JSON_METADATA_FIELDS = {"knowledge_points", "learner_levels", "source_urls"}
@dataclass(frozen=True)
class LexicalIndex:
    """Reusable KB-scoped BM25 corpus statistics.

    Chroma mutations invalidate the whole object, which keeps dense and lexical
    snapshots aligned while avoiding corpus tokenization for every query.
    """

    documents: tuple[Document, ...]
    tokenized_documents: tuple[tuple[str, ...], ...]
    term_frequencies: tuple[Counter[str], ...]
    document_frequency: Counter[str]
    average_length: float
    corpus_size: int
    snapshot_identity: str


_LEXICAL_INDEX_CACHE: dict[str, LexicalIndex] = {}
# Compatibility alias for tests/extensions from the previous cache generation.
_LEXICAL_DOCUMENT_CACHE = _LEXICAL_INDEX_CACHE
_LATIN_OR_NUMBER_TOKEN = re.compile(r"[a-z0-9]+(?:[._:/+\-][a-z0-9]+)*", re.IGNORECASE)
_CHINESE_SEQUENCE = re.compile(r"[\u4e00-\u9fff]+")
_BM25_K1 = 1.5
_BM25_B = 0.75
_RRF_K = 60


def _to_chroma_document(document: Document) -> Document:
    metadata = {}
    for key, value in document.metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            metadata[key] = value
        else:
            metadata[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return Document(page_content=document.page_content, metadata=metadata)


def _restore_retrieved_metadata(document: Document) -> Document:
    """Restore JSON-encoded provenance lists before returning search results."""
    for key in _JSON_METADATA_FIELDS:
        value = document.metadata.get(key)
        if isinstance(value, str):
            try:
                decoded = json.loads(value)
            except json.JSONDecodeError:
                continue
            if isinstance(decoded, list):
                document.metadata[key] = decoded
    return document


def _to_vector_candidate_metadata(metadata: dict[str, object]) -> dict[str, str | int | float | bool]:
    """Convert retrieval metadata to VectorCandidate's scalar-only schema."""
    candidate_metadata: dict[str, str | int | float | bool] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            candidate_metadata[key] = value
        else:
            candidate_metadata[key] = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return candidate_metadata


def _tokenize_for_lexical_search(text: str) -> list[str]:
    """Tokenize mixed Chinese/technical text without an external tokenizer.

    Latin identifiers, versions and error codes are retained as complete tokens.
    Chinese sequences contribute unigrams and bigrams so exact terminology can
    be matched even when the source and query use different sentence boundaries.
    """
    normalized = text.lower()
    tokens = _LATIN_OR_NUMBER_TOKEN.findall(normalized)
    for sequence in _CHINESE_SEQUENCE.findall(normalized):
        tokens.extend(sequence)
        tokens.extend(sequence[index:index + 2] for index in range(len(sequence) - 1))
    return tokens


def _bm25_search(
    query: str,
    documents: LexicalIndex | list[Document],
    top_k: int,
) -> list[tuple[Document, float]]:
    """Rank an in-memory knowledge-base corpus with Okapi BM25."""
    if top_k <= 0:
        return []
    index = documents if isinstance(documents, LexicalIndex) else _build_lexical_index(documents)
    if not index.documents:
        return []
    query_tokens = list(dict.fromkeys(_tokenize_for_lexical_search(query)))
    if not query_tokens:
        return []
    if index.average_length <= 0:
        return []
    scored: list[tuple[Document, float]] = []
    for document, tokens, term_frequency in zip(
        index.documents,
        index.tokenized_documents,
        index.term_frequencies,
    ):
        if not tokens:
            continue
        length_normalization = _BM25_K1 * (
            1 - _BM25_B + _BM25_B * len(tokens) / index.average_length
        )
        score = 0.0
        for token in query_tokens:
            frequency = term_frequency.get(token, 0)
            if not frequency:
                continue
            frequency_in_corpus = index.document_frequency[token]
            inverse_document_frequency = math.log(
                1
                + (index.corpus_size - frequency_in_corpus + 0.5)
                / (frequency_in_corpus + 0.5)
            )
            score += inverse_document_frequency * (
                frequency * (_BM25_K1 + 1) / (frequency + length_normalization)
            )
        if score > 0:
            scored.append((document, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def _build_lexical_index(
    documents: list[Document],
    *,
    snapshot_identity: str = "ad-hoc",
) -> LexicalIndex:
    tokenized = tuple(
        tuple(_tokenize_for_lexical_search(document.page_content)) for document in documents
    )
    frequencies = tuple(Counter(tokens) for tokens in tokenized)
    document_frequency: Counter[str] = Counter()
    for tokens in tokenized:
        document_frequency.update(set(tokens))
    average_length = (
        sum(len(tokens) for tokens in tokenized) / len(tokenized) if tokenized else 0.0
    )
    return LexicalIndex(
        documents=tuple(documents),
        tokenized_documents=tokenized,
        term_frequencies=frequencies,
        document_frequency=document_frequency,
        average_length=average_length,
        corpus_size=len(documents),
        snapshot_identity=snapshot_identity,
    )


def _load_lexical_index(
    store: Chroma,
    knowledge_base_id: str,
    *,
    profile: dict[str, object] | None = None,
) -> LexicalIndex:
    cached = _LEXICAL_INDEX_CACHE.get(knowledge_base_id)
    if cached is not None:
        if profile is not None:
            profile.update(lexical_cache_status="hit", lexical_load_ms=0.0, bm25_prepare_ms=0.0)
        return cached

    load_started = perf_counter()
    payload = store.get(include=["documents", "metadatas"])
    load_ms = round((perf_counter() - load_started) * 1000, 3)
    ids = payload.get("ids") or []
    texts = payload.get("documents") or []
    metadatas = payload.get("metadatas") or []
    documents: list[Document] = []
    for index, text in enumerate(texts):
        if not text:
            continue
        metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
        if index < len(ids):
            metadata.setdefault("chunk_id", ids[index])
        documents.append(
            _restore_retrieved_metadata(Document(page_content=text, metadata=metadata))
        )
    identity_payload = {
        "ids": [str(value) for value in ids],
        "versions": [str(document.metadata.get("document_version") or "") for document in documents],
    }
    snapshot_identity = hashlib.sha256(
        json.dumps(identity_payload, sort_keys=True).encode("utf-8")
    ).hexdigest()
    prepare_started = perf_counter()
    index = _build_lexical_index(documents, snapshot_identity=snapshot_identity)
    prepare_ms = round((perf_counter() - prepare_started) * 1000, 3)
    _LEXICAL_INDEX_CACHE[knowledge_base_id] = index
    if profile is not None:
        profile.update(
            lexical_cache_status="build",
            lexical_load_ms=load_ms,
            bm25_prepare_ms=prepare_ms,
            lexical_snapshot_hash=snapshot_identity[:20],
        )
    return index


def _load_lexical_documents(store: Chroma, knowledge_base_id: str) -> list[Document]:
    """Compatibility projection for callers that still request only documents."""

    return list(_load_lexical_index(store, knowledge_base_id).documents)


def _result_key(document: Document) -> str:
    return str(
        document.metadata.get("chunk_id")
        or hashlib.sha256(document.page_content.encode("utf-8")).hexdigest()
    )


def get_vector_store(knowledge_base_id: Optional[str] = None) -> Chroma:
    """获取指定知识库独立的持久化向量集合。"""
    settings = get_settings()
    vector_store_dir = resolve_backend_path(settings.vector_store_dir)
    os.makedirs(vector_store_dir, exist_ok=True)
    kb_id = _resolve_knowledge_base_id(knowledge_base_id)
    return Chroma(
        collection_name=_collection_name(kb_id, settings),
        persist_directory=str(vector_store_dir),
        embedding_function=get_embeddings(),
        collection_metadata={
            "knowledge_base_id": kb_id,
            "index_schema_version": "1.0",
            "hnsw:space": settings.vector_distance_metric,
        },
    )


def add_documents(documents: Iterable, ids: Optional[list[str]] = None, knowledge_base_id: Optional[str] = None):
    """以稳定 ID 上插入文档；重复执行同一批入库操作不会新增重复片段。"""
    documents = list(documents)
    if not documents:
        return []
    inferred_ids = {document.metadata.get("knowledge_base_id") for document in documents}
    if None in inferred_ids or len(inferred_ids) != 1:
        raise ValueError("一次入库只能包含同一 knowledge_base_id 的完整溯源片段")
    kb_id = _resolve_knowledge_base_id(knowledge_base_id or next(iter(inferred_ids)))
    if kb_id not in inferred_ids:
        raise ValueError("传入的 knowledge_base_id 与片段元数据不一致")
    stable_ids = ids or [document.metadata.get("chunk_id") for document in documents]
    if not all(stable_ids) or len(stable_ids) != len(documents):
        raise ValueError("每个片段必须具备唯一的 chunk_id")
    chroma_documents = [_to_chroma_document(document) for document in documents]
    result = get_vector_store(kb_id).add_documents(chroma_documents, ids=stable_ids)
    _LEXICAL_INDEX_CACHE.pop(kb_id, None)
    return result


def synchronize_documents(
    documents: Iterable,
    *,
    knowledge_base_id: Optional[str] = None,
) -> list[str]:
    """Replace one KB's active vector records with the supplied snapshot."""

    documents = list(documents)
    inferred_ids = {
        document.metadata.get("knowledge_base_id") for document in documents
    }
    if documents and (None in inferred_ids or len(inferred_ids) != 1):
        raise ValueError("一次同步只能包含同一 knowledge_base_id 的完整溯源片段")
    inferred_id = next(iter(inferred_ids)) if inferred_ids else None
    kb_id = _resolve_knowledge_base_id(knowledge_base_id or inferred_id)
    if inferred_id is not None and inferred_id != kb_id:
        raise ValueError("传入的 knowledge_base_id 与片段元数据不一致")

    stable_ids = [str(document.metadata.get("chunk_id") or "") for document in documents]
    if any(not item for item in stable_ids) or len(stable_ids) != len(set(stable_ids)):
        raise ValueError("每个片段必须具备唯一的 chunk_id")

    store = get_vector_store(kb_id)
    existing = store.get(include=[]).get("ids", [])
    if existing:
        store.delete(ids=list(existing))
    if documents:
        store.add_documents(
            [_to_chroma_document(document) for document in documents],
            ids=stable_ids,
        )
    _LEXICAL_INDEX_CACHE.pop(kb_id, None)
    return stable_ids


def vector_store_count(knowledge_base_id: Optional[str] = None) -> int:
    return int(get_vector_store(knowledge_base_id)._collection.count())


def reset_vector_store(knowledge_base_id: Optional[str] = None) -> None:
    """删除指定知识库的向量集合，用于显式全量重建。"""
    kb_id = _resolve_knowledge_base_id(knowledge_base_id)
    get_vector_store(kb_id).delete_collection()
    _LEXICAL_INDEX_CACHE.pop(kb_id, None)


def similarity_search(query: str, top_k: int = 5, knowledge_base_id: Optional[str] = None):
    """在指定知识库的独立集合中执行语义检索。"""
    if not query or not query.strip():
        raise ValueError("检索查询不能为空")
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    results = get_vector_store(knowledge_base_id).similarity_search_with_score(query, k=top_k)
    return [(_restore_retrieved_metadata(document), score) for document, score in results]


class ChromaVectorSearchBackend:
    """Raw KB-scoped candidate adapter used by EvidenceRetriever."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.last_profile: dict[str, object] = {}

    def search(
        self,
        *,
        query: str,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]:
        return self.search_many(
            queries=[query],
            top_k=top_k,
            knowledge_base_id=knowledge_base_id,
        )

    def search_many(
        self,
        *,
        queries: list[str],
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]:
        """Fuse per-query candidates, then execute one bounded CrossEncoder batch."""

        if not queries or any(not query.strip() for query in queries):
            raise ValueError("retrieval queries cannot be empty")
        from app.core.retrieval.reranker import mark_rerank_fallback, rerank_documents

        started = perf_counter()
        query_profiles: list[dict[str, object]] = []
        partial_failures = 0
        merged: dict[str, tuple[str, int, int, Document, float]] = {}
        per_query_k = max(top_k, self.settings.rerank_per_query_k)
        for query_index, query in enumerate(queries):
            query_profile: dict[str, object] = {
                "query_hash": hashlib.sha256(query.encode("utf-8")).hexdigest()[:20]
            }
            query_started = perf_counter()
            try:
                results = hybrid_search(
                    query,
                    top_k=per_query_k,
                    knowledge_base_id=knowledge_base_id,
                    profile=query_profile,
                )
                for hybrid_rank, (document, score) in enumerate(results, start=1):
                    key = _result_key(document)
                    candidate = (query, query_index, hybrid_rank, document, float(score))
                    previous = merged.get(key)
                    if previous is None or (score, -query_index, -hybrid_rank) > (
                        previous[4],
                        -previous[1],
                        -previous[2],
                    ):
                        merged[key] = candidate
            except Exception as exc:
                partial_failures += 1
                query_profile.update(
                    query_status="failed",
                    fallback_reason="hybrid_search_unavailable",
                    exception_type=type(exc).__name__,
                    # Keep the concrete backend detail in the internal
                    # retrieval profile so live acceptance reports can
                    # distinguish a provider failure from a local Chroma or
                    # embedding-runtime failure.  This is never exposed as a
                    # public error message.
                    exception_detail=str(exc)[:512],
                )
            query_profile["query_total_ms"] = round(
                (perf_counter() - query_started) * 1000, 3
            )
            query_profiles.append(query_profile)

        pool = sorted(
            merged.values(),
            key=lambda item: (-item[4], item[1], item[2], _result_key(item[3])),
        )[: self.settings.rerank_candidate_k]
        profile: dict[str, object] = {
            "query_count": len(queries),
            "query_profiles": query_profiles,
            "partial_failure_count": partial_failures,
            "unique_candidate_count": len(merged),
            "bounded_candidate_count": len(pool),
        }
        if not pool:
            self.last_profile = {
                **profile,
                "total_retrieval_ms": round((perf_counter() - started) * 1000, 3),
            }
            if partial_failures == len(queries):
                raise RuntimeError("RETRIEVAL_ALL_QUERIES_FAILED")
            return []

        hybrid_results = [(item[3], item[4]) for item in pool]
        pair_queries = [item[0] for item in pool]
        try:
            results = rerank_documents(
                pair_queries,
                hybrid_results,
                top_k=len(hybrid_results),
                profile=profile,
            )
        except Exception as exc:
            profile.update(
                rerank_status="fallback",
                fallback_reason="reranker_unavailable",
                rerank_candidate_count=len(hybrid_results),
                rerank_fallback_count=1,
            )
            results = mark_rerank_fallback(hybrid_results, len(hybrid_results), "unavailable")
            logger.warning(
                "Retrieval rerank fallback kb_id=%s query_count=%s reason=%s exception_type=%s",
                knowledge_base_id,
                len(queries),
                "reranker_unavailable",
                type(exc).__name__,
            )
        origin_by_chunk = {_result_key(item[3]): item for item in pool}
        selected: list[tuple[str, int, Document, float]] = []
        per_query_counts: dict[str, int] = {}
        for document, score in results:
            origin = origin_by_chunk[_result_key(document)]
            query = origin[0]
            count = per_query_counts.get(query, 0)
            if count >= top_k:
                continue
            per_query_counts[query] = count + 1
            selected.append((query, count + 1, document, float(score)))

        profile["final_candidate_count"] = len(selected)
        profile["total_retrieval_ms"] = round((perf_counter() - started) * 1000, 3)
        self.last_profile = profile
        logger.info(
            "Retrieval request profile kb_id=%s query_count=%s metrics=%s",
            knowledge_base_id,
            len(queries),
            profile,
        )
        return [
            VectorCandidate(
                chunk_id=str(document.metadata.get("chunk_id") or ""),
                text=document.page_content,
                metadata=_to_vector_candidate_metadata(document.metadata),
                raw_score=2.0 * float(score) - 1.0,
                score_kind=ScoreKind.SIMILARITY,
                metric=self.settings.vector_distance_metric,
                query=query,
                query_rank=query_rank,
            )
            for query, query_rank, document, score in selected
        ]


def hybrid_search(
    query: str,
    top_k: int = 5,
    knowledge_base_id: Optional[str] = None,
    *,
    profile: dict[str, object] | None = None,
):
    """Fuse dense vector retrieval and lexical BM25 ranking with RRF.

    The returned score is a normalized RRF relevance score in ``[0, 1]`` where
    larger is better. Channel-specific ranks and raw scores remain available in
    document metadata for tracing and evaluation.
    """
    if not query or not query.strip():
        raise ValueError("检索查询不能为空")
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")

    kb_id = _resolve_knowledge_base_id(knowledge_base_id)
    total_started = perf_counter()
    store = get_vector_store(kb_id)
    candidate_k = max(20, top_k * 4)
    vector_error: Exception | None = None
    lexical_error: Exception | None = None

    try:
        dense_started = perf_counter()
        vector_results = store.similarity_search_with_score(query, k=candidate_k)
        vector_results = [
            (_restore_retrieved_metadata(document), float(score))
            for document, score in vector_results
        ]
    except Exception as exc:
        vector_error = exc
        vector_results = []
    finally:
        if profile is not None:
            profile["dense_search_ms"] = round((perf_counter() - dense_started) * 1000, 3)

    try:
        lexical_index = _load_lexical_index(store, kb_id, profile=profile)
        bm25_started = perf_counter()
        lexical_results = _bm25_search(query, lexical_index, candidate_k)
        if profile is not None:
            profile["bm25_query_ms"] = round((perf_counter() - bm25_started) * 1000, 3)
    except Exception as exc:
        lexical_error = exc
        lexical_results = []

    if not vector_results and not lexical_results and (vector_error or lexical_error):
        raise vector_error or lexical_error  # type: ignore[misc]

    fused: dict[str, dict[str, object]] = {}
    fusion_started = perf_counter()
    for rank, (document, score) in enumerate(vector_results, start=1):
        key = _result_key(document)
        fused[key] = {
            "document": document,
            "vector_rank": rank,
            "vector_score": score,
            "lexical_rank": None,
            "lexical_score": None,
            "fusion_score": 1 / (_RRF_K + rank),
        }

    for rank, (document, score) in enumerate(lexical_results, start=1):
        key = _result_key(document)
        entry = fused.setdefault(
            key,
            {
                "document": document,
                "vector_rank": None,
                "vector_score": None,
                "lexical_rank": None,
                "lexical_score": None,
                "fusion_score": 0.0,
            },
        )
        entry["lexical_rank"] = rank
        entry["lexical_score"] = float(score)
        entry["fusion_score"] = float(entry["fusion_score"]) + 1 / (_RRF_K + rank)

    maximum_rrf_score = 2 / (_RRF_K + 1)
    ranked = sorted(
        fused.values(),
        key=lambda item: (
            float(item["fusion_score"]),
            -(int(item["vector_rank"]) if item["vector_rank"] is not None else candidate_k + 1),
            -(int(item["lexical_rank"]) if item["lexical_rank"] is not None else candidate_k + 1),
        ),
        reverse=True,
    )

    results: list[tuple[Document, float]] = []
    for item in ranked[:top_k]:
        source_document = item["document"]
        if not isinstance(source_document, Document):
            continue
        document = Document(
            page_content=source_document.page_content,
            metadata=dict(source_document.metadata),
        )
        normalized_score = min(1.0, float(item["fusion_score"]) / maximum_rrf_score)
        channels = []
        if item["vector_rank"] is not None:
            channels.append("vector")
        if item["lexical_rank"] is not None:
            channels.append("bm25")
        document.metadata.update(
            {
                "retrieval_method": "hybrid_rrf",
                "retrieval_channels": channels,
                "hybrid_score": normalized_score,
                "vector_rank": item["vector_rank"],
                "vector_score": item["vector_score"],
                "lexical_rank": item["lexical_rank"],
                "lexical_score": item["lexical_score"],
            }
        )
        results.append((document, normalized_score))
    if profile is not None:
        profile["hybrid_fusion_ms"] = round((perf_counter() - fusion_started) * 1000, 3)
        profile["hybrid_candidate_count"] = len(results)
        profile["hybrid_total_ms"] = round((perf_counter() - total_started) * 1000, 3)
    return results
