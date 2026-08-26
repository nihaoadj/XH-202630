from datetime import datetime, timezone

import pytest

from app.config import Settings
from app.core.retrieval.retriever import EvidenceRetriever
from app.core.security.errors import ErrorCode
from app.core.retrieval.knowledge_ids import (
    chunk_id,
    chunking_config_hash,
    document_version_id,
    normalize_text,
    sha256_hex,
)
from app.db.knowledge.memory import MemoryKnowledgeChunkRepository
from app.models.knowledge.knowledge import (
    KnowledgeChunk,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalStatus,
    ScoreKind,
    SourceLocator,
    SourceType,
    VectorCandidate,
)
from tests.fakes.evidence import ScriptedVectorSearchBackend


NOW = datetime(2026, 7, 29, tzinfo=timezone.utc)


def _chunk(kb_id="kb-one", document_id="doc-one", text="可信证据"):
    text = normalize_text(text)
    text_hash = sha256_hex(text)
    version = document_version_id(kb_id, document_id, sha256_hex(f"document:{text}"))
    config_hash = chunking_config_hash({"strategy": "test", "size": 100})
    stable_chunk_id = chunk_id(
        knowledge_base_id=kb_id,
        logical_document_id=document_id,
        document_version=version,
        chunking_hash=config_hash,
        ordinal=0,
        text_hash=text_hash,
    )
    locator = SourceLocator(
        knowledge_base_id=kb_id,
        document_id=document_id,
        document_version=version,
        chunk_id=stable_chunk_id,
        source_type=SourceType.MARKDOWN,
        source_path=f"{document_id}.md",
        title=document_id,
        section="测试",
        line_start=1,
        line_end=1,
    )
    return KnowledgeChunk(
        knowledge_base_id=kb_id,
        document_id=document_id,
        document_version=version,
        chunk_id=stable_chunk_id,
        ordinal=0,
        text=text,
        text_hash=text_hash,
        chunking_config_hash=config_hash,
        locator=locator,
    )


def _candidate(chunk, query, raw_score, *, query_rank=1, kb_id=None, metric="cosine"):
    return VectorCandidate(
        chunk_id=chunk.chunk_id,
        text=chunk.text,
        metadata={
            "knowledge_base_id": kb_id or chunk.knowledge_base_id,
            "document_id": chunk.document_id,
            "document_version": chunk.document_version,
            "chunk_id": chunk.chunk_id,
            "text_hash": chunk.text_hash,
        },
        raw_score=raw_score,
        score_kind=ScoreKind.DISTANCE,
        metric=metric,
        query=query,
        query_rank=query_rank,
    )


def _request(queries=None, **policy_overrides):
    return RetrievalRequest(
        run_id="run-one",
        step_id="step-one",
        knowledge_base_id="kb-one",
        queries=queries or ["query-one"],
        policy=RetrievalPolicy(**policy_overrides),
    )


def _retriever(backend, chunks):
    return EvidenceRetriever(
        backend=backend,
        chunk_repository=MemoryKnowledgeChunkRepository(chunks),
        settings=Settings(_env_file=None, embedding_model="fake-embedding"),
        clock=lambda: NOW,
    )


def test_evidence_retriever_normalizes_deduplicates_and_globally_ranks():
    first = _chunk(text="第一条")
    second = _chunk(document_id="doc-two", text="第二条")
    backend = ScriptedVectorSearchBackend({
        "query-one": [
            _candidate(first, "query-one", 0.4, query_rank=1),
            _candidate(second, "query-one", 0.2, query_rank=2),
        ],
        "query-two": [_candidate(first, "query-two", 0.1, query_rank=1)],
    })
    retriever = _retriever(backend, [first, second])

    result = retriever.retrieve(_request(["query-one", "query-two"]))

    assert result.status == RetrievalStatus.AVAILABLE
    assert result.candidate_count == 3
    assert [item.chunk_id for item in result.evidence] == [first.chunk_id, second.chunk_id]
    assert [item.rank for item in result.evidence] == [1, 2]
    assert result.evidence[0].query == "query-two"
    assert result.evidence[0].normalized_score == pytest.approx(0.95)
    assert result.evidence[1].normalized_score == pytest.approx(0.9)
    assert result.evidence[0].evidence_id.startswith("ev_")


def test_no_hit_is_distinct_from_retrieval_error():
    no_hit = _retriever(ScriptedVectorSearchBackend({}), []).retrieve(_request())
    failed = _retriever(
        ScriptedVectorSearchBackend({"query-one": RuntimeError("secret")}),
        [],
    ).retrieve(_request())

    assert no_hit.status == RetrievalStatus.NO_HIT
    assert no_hit.error is None
    assert failed.status == RetrievalStatus.RETRIEVAL_ERROR
    assert failed.error.code == ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE.value
    assert "secret" not in str(failed)


def test_candidates_below_threshold_are_evidence_insufficient():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": [_candidate(chunk, "query-one", 1.8)],
    })

    result = _retriever(backend, [chunk]).retrieve(
        _request(min_normalized_score=0.5)
    )

    assert result.status == RetrievalStatus.EVIDENCE_INSUFFICIENT
    assert result.error.code == ErrorCode.EVIDENCE_INSUFFICIENT.value
    assert result.evidence == []


def test_cross_kb_candidate_fails_closed():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": [_candidate(chunk, "query-one", 0.1, kb_id="kb-two")],
    })

    result = _retriever(backend, [chunk]).retrieve(_request())

    assert result.status == RetrievalStatus.RETRIEVAL_ERROR
    assert result.error.code == ErrorCode.EVIDENCE_SCOPE_VIOLATION.value


def test_missing_sql_chunk_provenance_fails_closed():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": [_candidate(chunk, "query-one", 0.1)],
    })

    result = _retriever(backend, []).retrieve(_request())

    assert result.error.code == ErrorCode.EVIDENCE_PROVENANCE_INVALID.value


def test_unknown_score_metric_is_rejected():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": [_candidate(chunk, "query-one", 0.1, metric="l2")],
    })

    result = _retriever(backend, [chunk]).retrieve(_request())

    assert result.error.code == ErrorCode.RETRIEVAL_SCORE_UNSUPPORTED.value


def test_partial_query_failure_can_return_sufficient_evidence():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": RuntimeError("temporary"),
        "query-two": [_candidate(chunk, "query-two", 0.1)],
    })

    result = _retriever(backend, [chunk]).retrieve(
        _request(["query-one", "query-two"])
    )

    assert result.status == RetrievalStatus.AVAILABLE
    assert result.partial_failure_count == 1
    assert result.evidence[0].chunk_id == chunk.chunk_id


def test_partial_query_failure_without_sufficient_evidence_is_retrieval_error():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": RuntimeError("temporary"),
        "query-two": [_candidate(chunk, "query-two", 1.8)],
    })

    result = _retriever(backend, [chunk]).retrieve(
        _request(["query-one", "query-two"], min_normalized_score=0.5)
    )

    assert result.status == RetrievalStatus.RETRIEVAL_ERROR
    assert result.error.code == ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE.value


def test_backend_cannot_inject_unrequested_query_identity():
    chunk = _chunk()
    backend = ScriptedVectorSearchBackend({
        "query-one": [_candidate(chunk, "not-requested", 0.1)],
    })

    result = _retriever(backend, [chunk]).retrieve(_request())

    assert result.status == RetrievalStatus.RETRIEVAL_ERROR
    assert result.error.code == ErrorCode.RETRIEVAL_QUERY_INVALID.value
