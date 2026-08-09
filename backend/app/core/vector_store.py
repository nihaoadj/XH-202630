"""按知识库隔离的 Chroma 向量存储访问层。"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
import re
from typing import Iterable, Optional

from langchain_community.vectorstores import Chroma
from langchain.schema import Document

from app.config import Settings, get_settings, resolve_backend_path
from app.core.embeddings import get_embeddings
from app.core.knowledge_base import load_knowledge_base_manifest
from app.models.knowledge import ScoreKind, VectorCandidate


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
_LEXICAL_DOCUMENT_CACHE: dict[str, list[Document]] = {}
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
    documents: list[Document],
    top_k: int,
) -> list[tuple[Document, float]]:
    """Rank an in-memory knowledge-base corpus with Okapi BM25."""
    if not documents or top_k <= 0:
        return []
    query_tokens = list(dict.fromkeys(_tokenize_for_lexical_search(query)))
    if not query_tokens:
        return []

    tokenized_documents = [_tokenize_for_lexical_search(document.page_content) for document in documents]
    average_length = sum(len(tokens) for tokens in tokenized_documents) / len(tokenized_documents)
    if average_length <= 0:
        return []

    document_frequency: Counter[str] = Counter()
    for tokens in tokenized_documents:
        document_frequency.update(set(tokens))

    corpus_size = len(documents)
    scored: list[tuple[Document, float]] = []
    for document, tokens in zip(documents, tokenized_documents):
        if not tokens:
            continue
        term_frequency = Counter(tokens)
        length_normalization = _BM25_K1 * (
            1 - _BM25_B + _BM25_B * len(tokens) / average_length
        )
        score = 0.0
        for token in query_tokens:
            frequency = term_frequency.get(token, 0)
            if not frequency:
                continue
            frequency_in_corpus = document_frequency[token]
            inverse_document_frequency = math.log(
                1 + (corpus_size - frequency_in_corpus + 0.5) / (frequency_in_corpus + 0.5)
            )
            score += inverse_document_frequency * (
                frequency * (_BM25_K1 + 1) / (frequency + length_normalization)
            )
        if score > 0:
            scored.append((document, score))

    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]


def _load_lexical_documents(store: Chroma, knowledge_base_id: str) -> list[Document]:
    cached = _LEXICAL_DOCUMENT_CACHE.get(knowledge_base_id)
    if cached is not None:
        return cached

    payload = store.get(include=["documents", "metadatas"])
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
    _LEXICAL_DOCUMENT_CACHE[knowledge_base_id] = documents
    return documents


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
    _LEXICAL_DOCUMENT_CACHE.pop(kb_id, None)
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
    return stable_ids


def vector_store_count(knowledge_base_id: Optional[str] = None) -> int:
    return int(get_vector_store(knowledge_base_id)._collection.count())


def reset_vector_store(knowledge_base_id: Optional[str] = None) -> None:
    """删除指定知识库的向量集合，用于显式全量重建。"""
    kb_id = _resolve_knowledge_base_id(knowledge_base_id)
    get_vector_store(kb_id).delete_collection()
    _LEXICAL_DOCUMENT_CACHE.pop(kb_id, None)


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

    def search(
        self,
        *,
        query: str,
        top_k: int,
        knowledge_base_id: str,
    ) -> list[VectorCandidate]:
        if not query.strip():
            raise ValueError("retrieval query cannot be empty")
        from app.core.reranker import mark_rerank_fallback, rerank_documents

        candidate_k = max(top_k, self.settings.rerank_candidate_k)
        hybrid_results = hybrid_search(
            query,
            top_k=candidate_k,
            knowledge_base_id=knowledge_base_id,
        )
        try:
            results = rerank_documents(query, hybrid_results, top_k=top_k)
        except Exception:
            results = mark_rerank_fallback(hybrid_results, top_k, "unavailable")
        return [
            VectorCandidate(
                chunk_id=str(document.metadata.get("chunk_id") or ""),
                text=document.page_content,
                metadata=dict(document.metadata),
                raw_score=2.0 * float(score) - 1.0,
                score_kind=ScoreKind.SIMILARITY,
                metric=self.settings.vector_distance_metric,
                query=query,
                query_rank=rank,
            )
            for rank, (document, score) in enumerate(results, start=1)
        ]


def hybrid_search(query: str, top_k: int = 5, knowledge_base_id: Optional[str] = None):
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
    store = get_vector_store(kb_id)
    candidate_k = max(20, top_k * 4)
    vector_error: Exception | None = None
    lexical_error: Exception | None = None

    try:
        vector_results = store.similarity_search_with_score(query, k=candidate_k)
        vector_results = [
            (_restore_retrieved_metadata(document), float(score))
            for document, score in vector_results
        ]
    except Exception as exc:
        vector_error = exc
        vector_results = []

    try:
        lexical_documents = _load_lexical_documents(store, kb_id)
        lexical_results = _bm25_search(query, lexical_documents, candidate_k)
    except Exception as exc:
        lexical_error = exc
        lexical_results = []

    if not vector_results and not lexical_results and (vector_error or lexical_error):
        raise vector_error or lexical_error  # type: ignore[misc]

    fused: dict[str, dict[str, object]] = {}
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
    return results
