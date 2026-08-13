from types import SimpleNamespace

from langchain.schema import Document

from app.core import reranker, vector_store
from app.core.vector_store import _to_vector_candidate_metadata


def test_vector_candidate_metadata_serializes_non_scalar_values_and_omits_none():
    metadata = _to_vector_candidate_metadata(
        {
            "knowledge_points": ["RAG", "向量检索"],
            "retrieval_channels": ["vector", "bm25"],
            "rerank_rank": None,
            "source": "training",
            "score": 0.5,
        }
    )

    assert metadata == {
        "knowledge_points": '["RAG", "向量检索"]',
        "retrieval_channels": '["vector", "bm25"]',
        "source": "training",
        "score": 0.5,
    }


class _Store:
    def __init__(self, documents):
        self.documents = documents
        self.get_calls = 0
        self.deleted = []

    def get(self, include):
        self.get_calls += 1
        if include == []:
            return {"ids": [doc.metadata["chunk_id"] for doc in self.documents]}
        return {
            "ids": [doc.metadata["chunk_id"] for doc in self.documents],
            "documents": [doc.page_content for doc in self.documents],
            "metadatas": [doc.metadata for doc in self.documents],
        }

    def delete(self, ids):
        self.deleted.extend(ids)

    def add_documents(self, documents, ids):
        self.documents = documents

    def delete_collection(self):
        self.documents = []


def _document(chunk_id, text="RAG evidence"):
    return Document(
        page_content=text,
        metadata={
            "chunk_id": chunk_id,
            "knowledge_base_id": "kb",
            "document_id": f"doc-{chunk_id}",
            "document_version": "v1",
            "text_hash": "a" * 64,
        },
    )


def test_lexical_index_cache_build_hit_and_kb_isolation():
    vector_store._LEXICAL_INDEX_CACHE.clear()
    first = _Store([_document("c1")])
    second = _Store([_document("c2")])
    first_profile = {}
    hit_profile = {}

    one = vector_store._load_lexical_index(first, "kb-one", profile=first_profile)
    again = vector_store._load_lexical_index(first, "kb-one", profile=hit_profile)
    two = vector_store._load_lexical_index(second, "kb-two")

    assert one is again
    assert one is not two
    assert first.get_calls == 1
    assert first_profile["lexical_cache_status"] == "build"
    assert hit_profile["lexical_cache_status"] == "hit"


def test_synchronize_and_reset_invalidate_lexical_cache(monkeypatch):
    store = _Store([_document("old")])
    monkeypatch.setattr(vector_store, "get_vector_store", lambda knowledge_base_id: store)
    vector_store._LEXICAL_INDEX_CACHE["kb"] = vector_store._build_lexical_index(store.documents)

    vector_store.synchronize_documents([_document("new")], knowledge_base_id="kb")
    assert "kb" not in vector_store._LEXICAL_INDEX_CACHE

    vector_store._LEXICAL_INDEX_CACHE["kb"] = vector_store._build_lexical_index(store.documents)
    vector_store.reset_vector_store("kb")
    assert "kb" not in vector_store._LEXICAL_INDEX_CACHE


def test_multi_query_search_dedupes_bounds_and_calls_reranker_once(monkeypatch):
    settings = SimpleNamespace(
        rerank_per_query_k=2,
        rerank_candidate_k=3,
        vector_distance_metric="cosine",
    )
    backend = vector_store.ChromaVectorSearchBackend(settings)
    calls = {"rerank": 0, "hybrid_top_k": []}

    def fake_hybrid(query, top_k, knowledge_base_id, profile):
        calls["hybrid_top_k"].append(top_k)
        shared = _document("shared", f"shared {query}")
        unique = _document(f"{query}-unique", f"unique {query}")
        return [(shared, 0.9), (unique, 0.8)]

    def fake_rerank(queries, candidates, top_k, profile):
        calls["rerank"] += 1
        assert len(queries) == len(candidates) == 3
        profile.update(rerank_status="available", rerank_pair_count=3, rerank_fallback_count=0)
        return candidates

    monkeypatch.setattr(vector_store, "hybrid_search", fake_hybrid)
    monkeypatch.setattr(reranker, "rerank_documents", fake_rerank)

    results = backend.search_many(
        queries=["q1", "q2"],
        top_k=2,
        knowledge_base_id="kb",
    )

    assert calls == {"rerank": 1, "hybrid_top_k": [2, 2]}
    assert len({item.chunk_id for item in results}) == len(results) == 3
    assert all(item.query_rank <= 2 for item in results)
    assert backend.last_profile["unique_candidate_count"] == 3
    assert backend.last_profile["bounded_candidate_count"] == 3
