import math
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from types import SimpleNamespace

import pytest
from langchain.schema import Document

from app.core.retrieval import reranker


def _settings(
    *,
    enabled: bool = True,
    max_per_document: int = 2,
    english_score_bonus: float = 0.08,
    minimum_score: float = 0.35,
):
    return SimpleNamespace(
        rerank_enabled=enabled,
        rerank_candidate_k=20,
        rerank_batch_size=4,
        rerank_max_chunks_per_document=max_per_document,
        rerank_model="BAAI/bge-reranker-base",
        retrieval_english_score_bonus=english_score_bonus,
        retrieval_min_normalized_score=minimum_score,
    )


class _FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs, **kwargs):
        self.pairs = pairs
        return self.scores


def _candidate(
    chunk_id: str,
    document_id: str,
    text: str,
    hybrid_score: float,
    *,
    source_path: str | None = None,
    source_path_verified: bool = False,
):
    metadata = {
        "chunk_id": chunk_id,
        "document_id": document_id,
        "hybrid_score": hybrid_score,
        "source_path_verified": source_path_verified,
    }
    if source_path is not None:
        metadata["source_path"] = source_path
    return (
        Document(
            page_content=text,
            metadata=metadata,
        ),
        hybrid_score,
    )


def _logit(probability: float) -> float:
    return math.log(probability / (1.0 - probability))


def test_build_rerank_query_contains_learning_context():
    query = reranker.build_rerank_query(
        "RAG 调优",
        target_skill_nodes=["混合检索"],
        weak_points=["RRF"],
        difficulty="进阶 RAG",
    )

    assert "学习主题：RAG 调优" in query
    assert "目标能力节点：混合检索" in query
    assert "需要补齐的知识点：RRF" in query
    assert "学习难度：进阶 RAG" in query


def test_rerank_documents_uses_cross_encoder_scores_and_audit_metadata(monkeypatch):
    model = _FakeCrossEncoder([0.0, 3.0, 1.0])
    monkeypatch.setattr(reranker, "get_settings", lambda: _settings())
    monkeypatch.setattr(reranker, "get_reranker", lambda: model)
    candidates = [
        _candidate("c1", "d1", "一般相关", 0.9),
        _candidate("c2", "d2", "最相关", 0.8),
        _candidate("c3", "d3", "次相关", 0.7),
    ]

    results = reranker.rerank_documents("查询", candidates, top_k=3)

    assert [document.metadata["chunk_id"] for document, _ in results] == ["c2", "c3", "c1"]
    first, score = results[0]
    assert model.pairs == [("查询", "一般相关"), ("查询", "最相关"), ("查询", "次相关")]
    assert first.metadata["retrieval_method"] == "hybrid_rrf_cross_encoder"
    assert first.metadata["rerank_status"] == "available"
    assert first.metadata["rerank_rank"] == 1
    assert first.metadata["rerank_raw_score"] == 3.0
    assert first.metadata["rerank_score"] == pytest.approx(score)
    assert score == pytest.approx(1 / (1 + 2.718281828459045 ** -3), rel=1e-5)


def test_verified_english_bonus_changes_selection_but_preserves_model_scores(monkeypatch):
    english_raw = _logit(0.70)
    chinese_raw = _logit(0.74)
    model = _FakeCrossEncoder([english_raw, chinese_raw])
    monkeypatch.setattr(reranker, "get_settings", lambda: _settings())
    monkeypatch.setattr(reranker, "get_reranker", lambda: model)
    candidates = [
        _candidate(
            "en",
            "doc-en",
            "eligible English passage",
            0.9,
            source_path="references/en/source.md",
            source_path_verified=True,
        ),
        _candidate(
            "zh",
            "doc-zh",
            "Chinese passage",
            0.8,
            source_path="references/zh/source.md",
            source_path_verified=True,
        ),
    ]

    results = reranker.rerank_documents("查询", candidates, top_k=2)
    by_chunk = {document.metadata["chunk_id"]: (document, score) for document, score in results}
    english, english_tuple_score = by_chunk["en"]
    chinese, chinese_tuple_score = by_chunk["zh"]

    assert [document.metadata["chunk_id"] for document, _ in results] == ["en", "zh"]
    assert english.metadata["source_language"] == "en"
    assert english.metadata["language_bonus"] == pytest.approx(0.08)
    assert english.metadata["selection_score"] == pytest.approx(0.78)
    assert english.metadata["selection_rank"] == 1
    assert english.metadata["rerank_raw_score"] == pytest.approx(english_raw)
    assert english.metadata["rerank_score"] == pytest.approx(0.70)
    assert english.metadata["final_score"] == pytest.approx(0.70)
    assert english.metadata["rerank_rank"] == 2
    assert english_tuple_score == pytest.approx(0.70)

    assert chinese.metadata["source_language"] == "zh"
    assert chinese.metadata["language_bonus"] == 0.0
    assert chinese.metadata["selection_score"] == pytest.approx(0.74)
    assert chinese.metadata["selection_rank"] == 2
    assert chinese.metadata["rerank_raw_score"] == pytest.approx(chinese_raw)
    assert chinese.metadata["rerank_score"] == pytest.approx(0.74)
    assert chinese.metadata["final_score"] == pytest.approx(0.74)
    assert chinese.metadata["rerank_rank"] == 1
    assert chinese_tuple_score == pytest.approx(0.74)


@pytest.mark.parametrize(
    ("relevance", "source_path", "verified", "bonus", "language", "expected_bonus"),
    [
        (0.34, "references/en/source.md", True, 0.08, "en", 0.0),
        (0.70, "references/en/source.md", True, 0.0, "en", 0.0),
        (0.70, "references/fr/source.md", True, 0.08, "unknown", 0.0),
        (0.70, "C:\\kb\\references\\en\\source.md", True, 0.08, "unknown", 0.0),
        (0.70, "references/en/../source.md", True, 0.08, "unknown", 0.0),
        (0.70, "references/en/source.md", False, 0.08, "unknown", 0.0),
    ],
)
def test_english_bonus_requires_qualified_verified_canonical_path(
    monkeypatch,
    relevance,
    source_path,
    verified,
    bonus,
    language,
    expected_bonus,
):
    monkeypatch.setattr(
        reranker,
        "get_settings",
        lambda: _settings(english_score_bonus=bonus),
    )
    monkeypatch.setattr(
        reranker,
        "get_reranker",
        lambda: _FakeCrossEncoder([_logit(relevance)]),
    )
    candidates = [
        _candidate(
            "one",
            "doc-one",
            "passage",
            0.5,
            source_path=source_path,
            source_path_verified=verified,
        )
    ]

    results = reranker.rerank_documents("查询", candidates, top_k=1)

    document, tuple_score = results[0]
    assert tuple_score == pytest.approx(relevance)
    assert document.metadata["rerank_score"] == pytest.approx(relevance)
    assert document.metadata["final_score"] == pytest.approx(relevance)
    assert document.metadata["rerank_rank"] == 1
    assert document.metadata["source_language"] == language
    assert document.metadata["language_bonus"] == pytest.approx(expected_bonus)
    assert document.metadata["selection_score"] == pytest.approx(relevance)


def test_higher_request_floor_prevents_bonus_before_top_k(monkeypatch):
    monkeypatch.setattr(reranker, "get_settings", lambda: _settings())
    monkeypatch.setattr(reranker, "get_reranker", lambda: _FakeCrossEncoder([_logit(0.75), _logit(0.80)]))
    english = _candidate("en", "en-doc", "English", 0.9,
                         source_path="references/en/source.md", source_path_verified=True)
    english[0].metadata["selection_min_relevance"] = 0.78
    chinese = _candidate("zh", "zh-doc", "中文", 0.8,
                         source_path="references/zh/source.md", source_path_verified=True)

    result = reranker.rerank_documents("查询", [english, chinese], top_k=1)

    assert result[0][0].metadata["chunk_id"] == "zh"
    assert result[0][1] == pytest.approx(0.80)


def test_rerank_diversity_limits_chunks_per_document(monkeypatch):
    monkeypatch.setattr(reranker, "get_settings", lambda: _settings(max_per_document=2))
    monkeypatch.setattr(reranker, "get_reranker", lambda: _FakeCrossEncoder([4.0, 3.0, 2.0, 1.0]))
    candidates = [
        _candidate("c1", "same", "同文档一", 0.9),
        _candidate("c2", "same", "同文档二", 0.8),
        _candidate("c3", "same", "同文档三", 0.7),
        _candidate("c4", "other", "其他文档", 0.6),
    ]

    results = reranker.rerank_documents("查询", candidates, top_k=3)

    assert [document.metadata["chunk_id"] for document, _ in results] == ["c1", "c2", "c4"]


def test_disabled_reranker_returns_hybrid_fallback(monkeypatch):
    monkeypatch.setattr(reranker, "get_settings", lambda: _settings(enabled=False))
    candidates = [
        _candidate(
            "c1",
            "d1",
            "片段",
            0.75,
            source_path="references/en/source.md",
            source_path_verified=True,
        )
    ]

    results = reranker.rerank_documents("查询", candidates, top_k=1)

    document, score = results[0]
    assert score == 0.75
    assert document.metadata["rerank_status"] == "disabled"
    assert document.metadata["retrieval_method"] == "hybrid_rrf"
    assert document.metadata["source_path_verified"] is False
    assert document.metadata["source_language"] == "unknown"
    assert document.metadata["language_bonus"] == 0.0
    assert document.metadata["selection_score"] == 0.75


def test_reranker_cold_load_is_single_flight(monkeypatch):
    calls = []
    model = _FakeCrossEncoder([1.0])

    reranker._load_reranker.cache_clear()

    @lru_cache(maxsize=1)
    def load_once():
        calls.append(1)
        return model

    monkeypatch.setattr(reranker, "_load_reranker", load_once)
    reranker._RERANKER_LOAD_FAILURE_AT = None

    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: reranker.get_reranker(), range(3)))

    assert results == [model, model, model]
    assert len(calls) == 1
