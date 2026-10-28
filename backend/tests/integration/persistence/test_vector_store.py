import math
from types import SimpleNamespace

import pytest

from langchain.schema import Document

from app.core.retrieval import reranker, vector_store
from app.core.retrieval.vector_store import _to_vector_candidate_metadata
from app.db.knowledge.memory import MemoryKnowledgeChunkRepository
from tests.fakes.evidence import make_knowledge_chunk


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

    def fake_hybrid(query, top_k, knowledge_base_id, profile, allowed_chunk_ids=None):
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


def _balanced_settings(**overrides):
    values = dict(rerank_per_query_k=2, rerank_candidate_k=4, vector_distance_metric="cosine",
                  rerank_enabled=True, retrieval_balanced_candidates_enabled=True, retrieval_dense_reserve=2)
    return SimpleNamespace(**{**values, **overrides})


def test_dense_floor_survives_global_cap_and_reranks_original_query_once(monkeypatch):
    from app.core.retrieval import query_expansion
    query = "Python 3.11 不要重建索引"
    monkeypatch.setattr(query_expansion, "expand_query", lambda *args: (["vector index"], {"query_expansion_status": "expanded"}))
    seen = []

    def hybrid(probe, top_k, knowledge_base_id, profile, allowed_chunk_ids=None, dense_candidate_collector=None):
        assert top_k == 4
        if dense_candidate_collector is not None:
            dense_candidate_collector.extend([(_document("english"), .3), (_document("dense-two"), .2)])
        if probe == "vector index":
            return [(_document("alias"), .99), (_document("english"), .95)]
        return [(_document("rrf-one"), .9), (_document("rrf-two"), .8)]

    def rerank(queries, candidates, top_k, profile):
        seen.append((queries, [d.metadata["chunk_id"] for d, _ in candidates]))
        assert queries == [query] * len(candidates)
        assert len(candidates) == top_k == 4
        profile.update(rerank_status="available", rerank_pair_count=4)
        return candidates

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid)
    monkeypatch.setattr(reranker, "rerank_documents", rerank)
    backend = vector_store.ChromaVectorSearchBackend(_balanced_settings())
    results = backend.search_many(queries=[query], top_k=4, knowledge_base_id="kb")
    assert len(seen) == 1
    assert {"english", "dense-two"} <= set(seen[0][1])
    assert len(results) == len({c.chunk_id for c in results}) == 4
    assert all(c.query == query for c in results)
    assert backend.last_profile["dense_protected_count"] == 2
    assert backend.last_profile["alias_probe_count"] == 1


def test_global_dense_reservation_is_round_robin_stable_and_language_neutral():
    def item(ident, score):
        return ("query", 0, 1, _document(ident), score)
    merged = {key: item(key, score) for key, score in [
        ("rrf", .99), ("a1", .5), ("a2", .4), ("b1", .1), ("b2", .05),
    ]}
    pool, protected = vector_store._bounded_candidate_pool(
        merged, [["a1", "a2"], ["b1", "b2"]], limit=3, reserve=2,
    )
    assert protected == 2
    assert {d.metadata["chunk_id"] for _, _, _, d, _ in pool} == {"rrf", "a1", "b1"}
    again, _ = vector_store._bounded_candidate_pool(
        dict(reversed(list(merged.items()))), [["a1", "a2"], ["b1", "b2"]], limit=3, reserve=2,
    )
    assert [x[3].metadata["chunk_id"] for x in pool] == [x[3].metadata["chunk_id"] for x in again]


@pytest.mark.parametrize("mode", ["unavailable", "disabled", "alias_failed"])
def test_optional_probe_and_rerank_failures_keep_original_only_fallback(monkeypatch, mode):
    from app.core.retrieval import query_expansion
    monkeypatch.setattr(query_expansion, "expand_query", lambda *args: (["alias"], {}))
    probes = []

    def hybrid(query, top_k, knowledge_base_id, profile, allowed_chunk_ids=None, dense_candidate_collector=None):
        probes.append(query)
        if query == "alias":
            if mode == "alias_failed":
                raise RuntimeError("alias temporarily unavailable")
            return [(_document("alias-only"), .99)]
        if dense_candidate_collector is not None:
            dense_candidate_collector.append((_document("original"), .4))
        return [(_document("original"), .7)]

    def rerank(queries, candidates, top_k, profile):
        if mode == "unavailable":
            raise RuntimeError("rerank unavailable")
        profile["rerank_status"] = "disabled" if mode == "disabled" else "available"
        return candidates

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid)
    monkeypatch.setattr(reranker, "rerank_documents", rerank)
    backend = vector_store.ChromaVectorSearchBackend(_balanced_settings(rerank_enabled=mode != "disabled"))
    results = backend.search(query="中文原问题", top_k=3, knowledge_base_id="kb")
    assert [x.chunk_id for x in results] == ["original"]
    assert all(x.query == "中文原问题" for x in results)
    assert backend.last_profile["partial_failure_count"] == 0
    if mode == "disabled":
        assert probes == ["中文原问题"]
    if mode == "unavailable":
        assert backend.last_profile["alias_fallback_excluded"] is True


def test_alias_and_dense_protection_cannot_widen_allowed_chunk_scope(monkeypatch):
    from app.core.retrieval import query_expansion
    monkeypatch.setattr(query_expansion, "expand_query", lambda *args: (["alias"], {}))
    filters = []

    def hybrid(query, top_k, knowledge_base_id, profile, allowed_chunk_ids=None, dense_candidate_collector=None):
        filters.append(allowed_chunk_ids)
        hits = [(_document("allowed"), .6), (_document("excluded"), .99)]
        if dense_candidate_collector is not None:
            dense_candidate_collector.extend(reversed(hits))
        return hits

    def rerank(queries, candidates, top_k, profile):
        assert [d.metadata["chunk_id"] for d, _ in candidates] == ["allowed"]
        profile["rerank_status"] = "available"
        return candidates

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid)
    monkeypatch.setattr(reranker, "rerank_documents", rerank)
    results = vector_store.ChromaVectorSearchBackend(_balanced_settings()).search(
        query="中文", top_k=3, knowledge_base_id="kb", allowed_chunk_ids={"allowed"},
    )
    assert filters == [{"allowed"}, {"allowed"}]
    assert [x.chunk_id for x in results] == ["allowed"]


def test_all_probes_failed_remains_a_retrieval_error(monkeypatch):
    from app.core.retrieval import query_expansion
    monkeypatch.setattr(query_expansion, "expand_query", lambda *args: (["alias"], {}))
    def fail(*args, **kwargs):
        raise RuntimeError("offline")
    monkeypatch.setattr(vector_store, "hybrid_search", fail)
    with pytest.raises(RuntimeError, match="RETRIEVAL_ALL_QUERIES_FAILED"):
        vector_store.ChromaVectorSearchBackend(_balanced_settings()).search(
            query="中文", top_k=3, knowledge_base_id="kb",
        )


def test_retrieval_configuration_versions_and_dense_budget_are_bound():
    from app.config import Settings
    from app.core.retrieval.retriever import _config_payload, retrieval_policy_from_settings
    from app.core.retrieval.selection import SELECTION_VERSION
    base = Settings(_env_file=None)
    policy = retrieval_policy_from_settings(base)
    assert policy.query_strategy_version == "deterministic-bilingual-v2"
    assert policy.ranking_strategy_version == SELECTION_VERSION
    first = _config_payload(base, policy, retrieval_scope="global")
    different = _config_payload(base.model_copy(update={"retrieval_dense_reserve": 5}), policy, retrieval_scope="global")
    assert first != different
    old = base.model_copy(update={
        "retrieval_balanced_candidates_enabled": False,
        "retrieval_english_score_bonus": 0.0,
    })
    assert retrieval_policy_from_settings(old).ranking_strategy_version == "normalized-score-v1"


def test_verified_search_resolves_full_pool_before_top_k_and_ignores_forged_path(monkeypatch):
    settings = SimpleNamespace(
        rerank_enabled=True,
        rerank_candidate_k=20,
        rerank_per_query_k=20,
        rerank_batch_size=20,
        rerank_max_chunks_per_document=20,
        rerank_model="fake-cross-encoder",
        retrieval_min_normalized_score=0.35,
        retrieval_english_score_bonus=0.08,
        retrieval_balanced_candidates_enabled=False,
        retrieval_dense_reserve=0,
        vector_distance_metric="cosine",
    )
    identifiers = ["sql-zh", "sql-en", *(f"sql-zh-{index}" for index in range(18))]
    trusted_sql_paths = {
        "sql-zh": "references/zh/guide.md",
        "sql-en": "references/en/guide.md",
        **{f"sql-zh-{index}": f"references/zh/extra-{index}.md" for index in range(18)},
    }
    sql_chunks = {
        ident: make_knowledge_chunk(
            knowledge_base_id="kb",
            document_id=f"doc-{ident}",
            document_version="v1",
            chunk_id=ident,
            text=ident,
            source_path=trusted_sql_paths[ident],
        )
        for ident in identifiers
    }
    memory_sql = MemoryKnowledgeChunkRepository(sql_chunks.values())
    candidate_scores = {"sql-zh": 0.74, "sql-en": 0.70}
    candidate_scores.update({ident: 0.20 for ident in identifiers[2:]})

    def logit(probability):
        return math.log(probability / (1.0 - probability))

    class _ScoreByChunkModel:
        def predict(self, pairs, **kwargs):
            return [logit(candidate_scores[passage]) for _query, passage in pairs]

    def hybrid_search(query, top_k, knowledge_base_id, profile, allowed_chunk_ids=None):
        assert top_k == 20
        return [
            (
                Document(
                    page_content=ident,
                    metadata={
                        "knowledge_base_id": "kb",
                        "chunk_id": ident,
                        "document_id": f"doc-{ident}",
                        "document_version": "v1",
                        "text_hash": sql_chunks[ident].text_hash,
                        "source_path": "references/en/chroma-forged.md",
                        "source_path_verified": True,
                        "language_bonus": 0.25,
                        "selection_score": 1.0,
                    },
                ),
                1.0 - index * 0.01,
            )
            for index, ident in enumerate(identifiers)
        ]

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid_search)
    monkeypatch.setattr(reranker, "get_settings", lambda: settings)
    monkeypatch.setattr(reranker, "get_reranker", lambda: _ScoreByChunkModel())
    backend = vector_store.ChromaVectorSearchBackend(settings)

    # The legacy signature must clear Chroma's forged verified bit before reranking.
    unverified = backend.search_many(
        queries=["英文候选"], top_k=1, knowledge_base_id="kb",
    )
    assert unverified[0].chunk_id == "sql-zh"
    assert unverified[0].metadata["source_path_verified"] is False
    assert unverified[0].metadata["source_language"] == "unknown"
    assert unverified[0].metadata["language_bonus"] == 0.0
    assert unverified[0].metadata["selection_score"] == pytest.approx(0.74)

    resolved = []

    def resolve_from_sql(query, document):
        metadata = document.metadata
        chunk = memory_sql.get_chunk(
            metadata["chunk_id"],
            knowledge_base_id=metadata["knowledge_base_id"],
            document_version=metadata["document_version"],
        )
        assert chunk is not None
        assert chunk.document_id == metadata["document_id"]
        assert chunk.text_hash == metadata["text_hash"]
        assert chunk.text == document.page_content
        resolved.append((query, metadata["chunk_id"]))
        return chunk.locator.source_path

    verified = backend.search_many_verified(
        queries=["英文候选"],
        top_k=1,
        knowledge_base_id="kb",
        source_path_resolver=resolve_from_sql,
    )

    assert {chunk_id for _query, chunk_id in resolved} == set(identifiers)
    assert len(resolved) == 20
    assert all(query == "英文候选" for query, _chunk_id in resolved)
    assert backend.last_profile["source_validation_stage"] == "sql_pre_top_k"
    assert backend.last_profile["source_validation_count"] == 20
    assert backend.last_profile["bounded_candidate_count"] == 20
    assert len(verified) == 1
    assert verified[0].chunk_id == "sql-en"
    assert verified[0].metadata["source_path"] == trusted_sql_paths["sql-en"]
    assert verified[0].metadata["source_path_verified"] is True
    assert verified[0].metadata["source_language"] == "en"
    assert verified[0].metadata["language_bonus"] == pytest.approx(0.08)
    assert verified[0].metadata["selection_score"] == pytest.approx(0.78)
    assert verified[0].metadata["rerank_score"] == pytest.approx(0.70)
    assert verified[0].metadata["rerank_rank"] == 2
    assert verified[0].metadata["selection_rank"] == 1


def test_dense_collector_exposes_ranks_without_changing_hybrid_top_k(monkeypatch):
    english = _document("english", "asymmetric semantic search query document encoding")
    chinese = [_document(f"zh-{i}", "中文检索 查询 编码") for i in range(4)]
    class Store(_Store):
        def similarity_search_with_score(self, query, k, filter=None):
            return [(english, .1), *[(d, .2+i*.01) for i, d in enumerate(chinese)]]
    store = Store([english, *chinese])
    vector_store._LEXICAL_INDEX_CACHE.clear()
    monkeypatch.setattr(vector_store, "get_vector_store", lambda _: store)
    collector = []
    result = vector_store.hybrid_search("中文检索 查询 编码", top_k=2, knowledge_base_id="kb",
                                       dense_candidate_collector=collector)
    assert len(result) == 2
    assert "english" not in {d.metadata["chunk_id"] for d, _ in result}
    assert collector[0][0].metadata["chunk_id"] == "english"
    assert collector[0][0].metadata["vector_rank"] == 1
    assert collector[0][0].metadata["lexical_rank"] is None
    assert all(0 < score <= 1 for _, score in collector)


def test_alias_fingerprint_changes_evidence_configuration_hash(monkeypatch):
    from app.config import Settings
    from app.core.retrieval import query_expansion
    from app.core.retrieval.knowledge_ids import retrieval_config_hash
    from app.core.retrieval.retriever import _config_payload, retrieval_policy_from_settings
    settings = Settings(_env_file=None)
    policy = retrieval_policy_from_settings(settings)
    fingerprint = {"query_expansion_config_hash": "a" * 64}
    monkeypatch.setattr(query_expansion, "expand_query", lambda *args: ([], dict(fingerprint)))
    first = retrieval_config_hash(_config_payload(settings, policy, retrieval_scope="global", knowledge_base_id="kb"))
    fingerprint["query_expansion_config_hash"] = "b" * 64
    second = retrieval_config_hash(_config_payload(settings, policy, retrieval_scope="global", knowledge_base_id="kb"))
    assert first != second
