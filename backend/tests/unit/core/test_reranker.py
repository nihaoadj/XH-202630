from types import SimpleNamespace

import pytest
from langchain.schema import Document

from app.core import reranker


def _settings(*, enabled: bool = True, max_per_document: int = 2):
    return SimpleNamespace(
        rerank_enabled=enabled,
        rerank_candidate_k=20,
        rerank_batch_size=4,
        rerank_max_chunks_per_document=max_per_document,
        rerank_model="BAAI/bge-reranker-base",
    )


class _FakeCrossEncoder:
    def __init__(self, scores):
        self.scores = scores
        self.pairs = None

    def predict(self, pairs, **kwargs):
        self.pairs = pairs
        return self.scores


def _candidate(chunk_id: str, document_id: str, text: str, hybrid_score: float):
    return (
        Document(
            page_content=text,
            metadata={
                "chunk_id": chunk_id,
                "document_id": document_id,
                "hybrid_score": hybrid_score,
            },
        ),
        hybrid_score,
    )


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
    candidates = [_candidate("c1", "d1", "片段", 0.75)]

    results = reranker.rerank_documents("查询", candidates, top_k=1)

    document, score = results[0]
    assert score == 0.75
    assert document.metadata["rerank_status"] == "disabled"
    assert document.metadata["retrieval_method"] == "hybrid_rrf"
