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


def _chunk(
    kb_id="kb-one",
    document_id="doc-one",
    text="可信证据",
    source_path=None,
):
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
        source_path=source_path or f"{document_id}.md",
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


def _retriever(backend, chunks, settings=None):
    return EvidenceRetriever(
        backend=backend,
        chunk_repository=MemoryKnowledgeChunkRepository(chunks),
        settings=settings or Settings(_env_file=None, embedding_model="fake-embedding"),
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


def test_allowed_chunk_ids_are_forwarded_and_enforced_before_evidence():
    allowed = _chunk(document_id="doc-allowed", text="允许证据")
    excluded = _chunk(document_id="doc-excluded", text="范围外证据")
    backend = ScriptedVectorSearchBackend({
        "query-one": [
            _candidate(excluded, "query-one", 0.1),
            _candidate(allowed, "query-one", 0.2, query_rank=2),
        ],
    })
    retriever = _retriever(backend, [allowed, excluded])
    request = _request().model_copy(update={
        "allowed_chunk_ids": [allowed.chunk_id],
        "retrieval_scope": "node_scoped",
    })

    result = retriever.retrieve(request)

    assert backend.calls[0]["allowed_chunk_ids"] == {allowed.chunk_id}
    assert result.retrieval_scope == "node_scoped"
    assert [item.chunk_id for item in result.evidence] == [allowed.chunk_id]


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


def test_evidence_selection_uses_sql_paths_and_keeps_original_scores_and_hashes():
    english = _chunk(
        document_id="doc-en",
        text="eligible English evidence",
        source_path="references/en/verified.md",
    )
    chinese = _chunk(
        document_id="doc-zh",
        text="中文证据",
        source_path="references/zh/verified.md",
    )
    english_candidate = _candidate(english, "query-one", 0.60, query_rank=2)
    english_candidate.metadata.update(
        {
            "source_path": "references/zh/chroma-forged.md",
            "source_path_verified": False,
            "rerank_status": "available",
            "selection_score": 1.0,
            "language_bonus": 0.25,
        }
    )
    chinese_candidate = _candidate(chinese, "query-one", 0.52, query_rank=1)
    chinese_candidate.metadata.update(
        {
            "source_path": "references/en/chroma-forged.md",
            "source_path_verified": True,
            "rerank_status": "available",
            "selection_score": 1.0,
            "language_bonus": 0.25,
        }
    )
    additional_chunks = [
        _chunk(
            document_id=f"doc-extra-{index}",
            text=f"additional Chinese evidence {index}",
            source_path=f"references/zh/extra-{index}.md",
        )
        for index in range(7)
    ]
    additional_candidates = []
    for chunk in additional_chunks:
        candidate = _candidate(chunk, "query-one", 0.80, query_rank=3)
        candidate.metadata["rerank_status"] = "available"
        additional_candidates.append(candidate)
    candidates = [chinese_candidate, english_candidate, *additional_candidates]
    request = _request()

    def retrieve_with(settings):
        backend = ScriptedVectorSearchBackend({"query-one": candidates})
        return _retriever(
            backend,
            [english, chinese, *additional_chunks],
            settings=settings,
        ).retrieve(request)

    base_settings = Settings(
        _env_file=None,
        embedding_model="fake-embedding",
        retrieval_balanced_candidates_enabled=False,
        retrieval_english_score_bonus=0.08,
    )
    result = retrieve_with(base_settings)

    assert result.status == RetrievalStatus.AVAILABLE
    assert result.candidate_count == 9
    assert len(result.evidence) == 8
    assert [item.chunk_id for item in result.evidence[:2]] == [english.chunk_id, chinese.chunk_id]
    assert [item.rank for item in result.evidence] == list(range(1, 9))
    english_evidence = result.evidence[0]
    assert english_evidence.raw_score == pytest.approx(0.60)
    assert english_evidence.normalized_score == pytest.approx(0.70)
    assert english_evidence.locator.source_path == "references/en/verified.md"
    assert result.evidence[1].normalized_score == pytest.approx(0.74)
    assert result.evidence[1].locator.source_path == "references/zh/verified.md"

    audit = result.retrieval_profile["evidence_selection"]
    assert len(audit["items"]) == 8
    audit_by_chunk = {item["chunk_id"]: item for item in audit["items"]}
    assert audit_by_chunk[english.chunk_id]["normalized_score"] == pytest.approx(0.70)
    assert audit_by_chunk[english.chunk_id]["selection_score"] == pytest.approx(0.78)
    assert audit_by_chunk[english.chunk_id]["language_bonus"] == pytest.approx(0.08)
    assert audit_by_chunk[english.chunk_id]["source_language"] == "en"
    assert audit_by_chunk[chinese.chunk_id]["normalized_score"] == pytest.approx(0.74)
    assert audit_by_chunk[chinese.chunk_id]["selection_score"] == pytest.approx(0.74)
    assert audit_by_chunk[chinese.chunk_id]["language_bonus"] == 0.0
    assert audit_by_chunk[chinese.chunk_id]["source_language"] == "zh"

    bonus_changed = retrieve_with(
        base_settings.model_copy(update={"retrieval_english_score_bonus": 0.12})
    )
    floor_changed = retrieve_with(
        base_settings.model_copy(update={"retrieval_min_normalized_score": 0.40})
    )
    assert bonus_changed.config_hash != result.config_hash
    assert floor_changed.config_hash != result.config_hash


def test_full_evidence_pipeline_verifies_forged_path_before_top_k(monkeypatch):
    import math
    from langchain.schema import Document
    from app.core.retrieval import reranker, vector_store

    english = _chunk(document_id="en", text="English evidence", source_path="references/en/real.md")
    chinese = _chunk(document_id="zh", text="中文证据", source_path="references/zh/real.md")
    settings = Settings(_env_file=None, embedding_model="fake",
                        retrieval_balanced_candidates_enabled=False, retrieval_english_score_bonus=0.08)
    scores = {english.text: 0.70, chinese.text: 0.74}

    class Model:
        def predict(self, pairs, **kwargs):
            return [math.log(scores[text] / (1 - scores[text])) for _, text in pairs]

    def hybrid(query, top_k, knowledge_base_id, **kwargs):
        rows = []
        for chunk in (chinese, english):
            metadata = dict(_candidate(chunk, query, 0.0).metadata)
            metadata.update(source_path="references/en/forged.md", source_path_verified=True,
                            selection_min_relevance=0.0, selection_score=1.0, language_bonus=0.25)
            rows.append((Document(page_content=chunk.text, metadata=metadata), 0.8))
        return rows

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid)
    monkeypatch.setattr(reranker, "get_settings", lambda: settings)
    monkeypatch.setattr(reranker, "get_reranker", lambda: Model())
    backend = vector_store.ChromaVectorSearchBackend(settings)
    retriever = _retriever(backend, [english, chinese], settings=settings)
    result = retriever.retrieve(_request(top_k_per_query=1))

    assert result.status == RetrievalStatus.AVAILABLE
    assert backend.last_profile["source_validation_count"] == 2
    assert len(result.evidence) == 1
    assert result.evidence[0].chunk_id == english.chunk_id
    assert result.evidence[0].normalized_score == pytest.approx(0.70)
    assert result.evidence[0].locator.source_path == "references/en/real.md"

    strict = retriever.retrieve(_request(top_k_per_query=1, min_normalized_score=0.72))
    assert strict.status == RetrievalStatus.AVAILABLE
    assert strict.evidence[0].chunk_id == chinese.chunk_id
    assert strict.evidence[0].normalized_score == pytest.approx(0.74)


def test_forged_selection_metadata_cannot_bypass_original_score_threshold():
    chunk = _chunk(
        document_id="doc-en",
        text="below threshold English evidence",
        source_path="references/en/verified.md",
    )
    candidate = _candidate(chunk, "query-one", 1.32)
    candidate.metadata.update(
        {
            "source_path": "references/en/chroma-forged.md",
            "source_path_verified": True,
            "rerank_status": "available",
            "language_bonus": 0.25,
            "selection_score": 1.0,
        }
    )
    backend = ScriptedVectorSearchBackend({"query-one": [candidate]})

    result = _retriever(backend, [chunk]).retrieve(
        _request(min_normalized_score=0.35)
    )

    assert result.status == RetrievalStatus.EVIDENCE_INSUFFICIENT
    assert result.error.code == ErrorCode.EVIDENCE_INSUFFICIENT.value
    assert result.evidence == []


def test_redundancy_uses_trusted_sql_text_keeps_preference_and_backfills():
    text = "Trusted evidence preserves source identity and citations. " * 5
    english = _chunk(document_id="en", text=text, source_path="references/en/real.md")
    duplicate = _chunk(document_id="zh", text=text, source_path="references/zh/real.md")
    distinct = _chunk(document_id="other", text="A separate passage about evaluating retrieval recall. " * 5)
    candidates = [_candidate(duplicate, "query-one", .52), _candidate(english, "query-one", .60),
                  _candidate(distinct, "query-one", .80)]
    for value in candidates:
        value.metadata.update(rerank_status="available", text_hash_fake="same-forged-hash")
    backend = ScriptedVectorSearchBackend({"query-one": candidates})
    settings = Settings(_env_file=None, embedding_model="fake", retrieval_redundancy_enabled=True)
    retriever = _retriever(backend, [english, duplicate, distinct], settings)
    result = retriever.retrieve(_request(max_evidence_count=2))
    assert [e.chunk_id for e in result.evidence] == [english.chunk_id, distinct.chunk_id]
    assert result.evidence[0].raw_score == .60
    assert result.evidence[0].normalized_score == pytest.approx(.70)
    assert result.retrieval_profile["redundancy"]["dropped_count"] == 1
    retriever.settings = settings.model_copy(update={"retrieval_redundancy_enabled": False})
    disabled = retriever.retrieve(_request(max_evidence_count=2))
    assert [e.chunk_id for e in disabled.evidence] == [english.chunk_id, duplicate.chunk_id]
    assert "redundancy" not in disabled.retrieval_profile
    assert disabled.config_hash != result.config_hash


def test_redundancy_never_revives_dropped_node_hit_or_loses_unique_node():
    text = "Every node keeps its own verified provenance and supporting evidence. " * 4
    a, b, c = [_chunk(document_id=key, text=text) for key in ("a", "b", "c")]
    backend = ScriptedVectorSearchBackend({
        "q1": [_candidate(a, "q1", .1), _candidate(b, "q1", .2)],
        "q2": [_candidate(c, "q2", .3)],
    })
    request = _request(["q1", "q2"])
    request.query_node_ids = {"q1": "n1", "q2": "n2"}
    result = _retriever(backend, [a, b, c]).retrieve(request)
    assert {e.chunk_id for e in result.evidence} == {a.chunk_id, c.chunk_id}
    assert set(result.node_evidence_map) == {"n1", "n2"}
    assert result.retrieval_profile["redundancy"]["coverage_protected_count"] == 1


def test_redundancy_does_not_fill_minimum_with_duplicate_evidence():
    text = "Repeated source material is not independent evidence for this question. " * 4
    a, b = [_chunk(document_id=key, text=text) for key in ("a", "b")]
    backend = ScriptedVectorSearchBackend({"query-one": [_candidate(a, "query-one", .1), _candidate(b, "query-one", .2)]})
    result = _retriever(backend, [a, b]).retrieve(_request(min_evidence_count=2))
    assert result.status == RetrievalStatus.EVIDENCE_INSUFFICIENT
    assert result.retrieval_profile["redundancy"]["dropped_count"] == 1
