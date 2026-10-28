"""Focused deterministic learning query/source/full-window checks; no models."""
from types import SimpleNamespace

from app.agents.shared.learning_queries import learning_queries
from app.agents.shared import retrieval
from app.config import Settings
from app.core.retrieval import retriever as retrieval_core
from app.core.retrieval.source_balance import (
    VERSION, SourceCandidate, catalog_hash, select_sources, source_role,
)
from app.models.knowledge.knowledge import RetrievalPolicy, RetrievalRequest
from app.models.knowledge.knowledge import RetrievalStatus
from tests.fakes.evidence import ScriptedEvidenceRetriever, make_available_batch, make_evidence, make_knowledge_chunk
from tests.integration.services.test_resource_aware_retrieval import setup_retriever


def inputs(**changes):
    return SimpleNamespace(**{"topic": "RAG", "target_skill_nodes": ["hybrid_retrieval"],
        "diagnosis": {}, "resource_types": ["实操指南"], **changes})


def descriptor(node):
    return node, ["technical_term"]


def test_questions_are_specific_bounded_and_cover_every_node_before_second_turn():
    value = inputs(target_skill_nodes=["a", "b", "c"])
    queries, mapping = learning_queries(value, descriptor, 6)
    assert len(queries) == 6 and "RAG" not in queries
    assert list(mapping.values()) == ["a", "b", "c", "a", "b", "c"]
    assert learning_queries(value, descriptor, 6) == (queries, mapping)
    assert "结果验证" in queries[-1]


def test_explicit_user_question_is_retained_and_node_task_is_not_just_topic():
    topic = "RRF 为什么不直接相加 BM25 和向量分数？"
    queries, mapping = learning_queries(inputs(topic=topic), descriptor, 6)
    assert queries[0] == topic and mapping[topic] == "hybrid_retrieval"
    assert "RRF" in queries[1] and len(queries) <= 6


def test_weaknesses_and_anchorless_requests_still_generate_bounded_tasks():
    queries, mapping = learning_queries(inputs(target_skill_nodes=[], diagnosis={"weak_points": ["余弦距离", "归一化"]}), descriptor, 6)
    assert len(queries) == 4 and not mapping and all("余弦距离" in q or "归一化" in q for q in queries)
    assert len(learning_queries(inputs(target_skill_nodes=[]), descriptor, 6)[0]) == 2


def test_overlong_or_unrepresentable_queries_use_explicit_fallback():
    assert learning_queries(inputs(topic="主" * 1999), descriptor, 6) is None
    assert learning_queries(inputs(target_skill_nodes=["a", "b"]), descriptor, 1) is None
    assert learning_queries(inputs(topic="具体问题？", target_skill_nodes=["a", "b"]), descriptor, 2) is None


def test_query_feature_switch_and_e1_fallback_preserve_original_policy():
    state = retrieval.RetrieverInput(topic="RAG", target_skill_nodes=["chunking"]).model_dump()
    for enabled in (True, False):
        fake = ScriptedEvidenceRetriever([make_available_batch([make_evidence()])],
            settings=Settings(_env_file=None, learning_retrieval_refinement_enabled=enabled))
        retrieval.retrieve_node(state, evidence_retriever=fake)
        assert (fake.calls[0].policy.ranking_strategy_version == VERSION) is enabled
        if not enabled:
            assert fake.calls[0].queries == retrieval._queries(retrieval.RetrieverInput.model_validate(state))[0]


def row(name, role="original", score=.9, *, document=None, nodes=()):
    return SourceCandidate(name, document or name, role, score, frozenset(nodes))


def test_source_roles_require_matching_manifest_and_trusted_canonical_path():
    specs = {"a": ("references/en/papers/a/content.md", "authoritative_original"),
             "module_x": ("teaching/zh/x.md", None)}
    assert source_role("a", specs["a"][0], specs) == "original"
    assert source_role("module_x", specs["module_x"][0], specs) == "teaching"
    assert source_role("a", "references/en/fake.md", specs) == "unknown"
    assert source_role("unlisted", specs["a"][0], specs) == "unknown"
    assert source_role("a", "references/en/../a.md", {"a": ("references/en/../a.md", "authoritative_original")}) == "unknown"
    assert catalog_hash(specs) == catalog_hash(dict(reversed(list(specs.items()))))


def test_source_balance_limits_teaching_and_preserves_relevant_originals():
    ranked = [row(f"t{i}", "teaching", .99-i*.01) for i in range(4)] + [row("a", score=.9), row("b", score=.89)]
    selected, audit = select_sources(ranked, budget=4, nodes=[], minimum_score=.35)
    assert selected == ["t0", "t1", "a", "b"]
    assert audit["selected_counts"] == {"teaching": 2, "original": 2}
    assert audit["baseline_relevance"] == ranked[3].relevance


def test_low_relevance_originals_are_not_forced_over_stronger_teaching():
    ranked = [row(f"t{i}", "teaching", .99-i*.01) for i in range(4)] + [row("weak", score=.36)]
    selected, audit = select_sources(ranked, budget=4, nodes=[], minimum_score=.35)
    assert selected == ["t0", "t1", "t2", "t3"]
    assert "original_shortfall" in audit["relaxations"] and "teaching_limit" in audit["relaxations"]


def test_node_coverage_is_harder_than_source_and_document_soft_limits():
    ranked = [row(f"t{i}", "teaching", .99-i*.01, document="one", nodes=[f"n{i}"]) for i in range(3)]
    selected, audit = select_sources(ranked, budget=3, nodes=["n0", "n1", "n2"], minimum_score=.35)
    assert selected == ["t0", "t1", "t2"] and not audit["uncovered_nodes"]
    assert "teaching_limit" in audit["relaxations"] and "document_limit" in audit["relaxations"]


def test_document_diversity_and_unknown_sources_never_forge_original_counts():
    ranked = [row(str(i), "unknown", .99-i*.01, document="same") for i in range(3)] + [row("other", "unknown", .9)]
    selected, audit = select_sources(ranked, budget=3, nodes=[], minimum_score=.35)
    assert selected == ["0", "1", "other"] and audit["selected_counts"].get("original", 0) == 0


def test_quality_precedes_document_diversity_when_alternatives_are_much_weaker():
    ranked = [row(str(i), score=.99-i*.01, document="same") for i in range(4)] + [row("weak", score=.36)]
    selected, audit = select_sources(ranked, budget=4, nodes=[], minimum_score=.35)
    assert selected == ["0", "1", "2", "3"] and "document_limit" in audit["relaxations"]
    assert "relative_floor_fill" not in audit["relaxations"]


def test_complete_pool_keeps_seventh_strong_owner_hit_and_node_coverage(monkeypatch):
    chunks = [make_knowledge_chunk(chunk_id=f"c{i}", document_id=f"doc{i}", text=f"事实{i}") for i in range(9)]
    hits = {"q1": [(c, .99-i*.01) for i, c in enumerate(chunks[:8])], "q2": [(chunks[8], .8)]}
    settings = Settings(_env_file=None, retrieval_balanced_candidates_enabled=False, retrieval_redundancy_enabled=False)
    instance, backend, _ = setup_retriever(monkeypatch, hits, settings=settings)
    monkeypatch.setattr(retrieval_core, "source_catalog", lambda kb: {})
    policy = RetrievalPolicy(top_k_per_query=6, max_evidence_count=8, ranking_strategy_version=VERSION)
    request = RetrievalRequest(run_id="r", step_id="s", knowledge_base_id="kb-fixture", queries=["q1", "q2"],
        query_node_ids={"q1": "a", "q2": "b"}, policy=policy)
    result = instance.retrieve(request)
    assert len(result.evidence) == 8 and chunks[6].chunk_id in {v.chunk_id for v in result.evidence}
    assert set(result.node_evidence_map) == {"a", "b"}
    assert backend.last_profile["final_candidate_count"] == 9
    assert result.retrieval_profile["learning_candidate_window"] == "full_pool"
    # Existing direct adapter API keeps its per-query quota unchanged.
    assert len(backend.search_many(queries=["q1"], top_k=6, knowledge_base_id="kb-fixture")) == 6


def test_single_query_budget_and_legacy_injected_adapter_remain_bounded(monkeypatch):
    chunks = [make_knowledge_chunk(chunk_id=f"c{i}", document_id=f"d{i}", text=f"依据{i}") for i in range(8)]
    settings = Settings(_env_file=None, retrieval_balanced_candidates_enabled=False)
    instance, _, _ = setup_retriever(monkeypatch, {"q": [(c, .99-i*.01) for i, c in enumerate(chunks)]}, settings=settings)
    monkeypatch.setattr(retrieval_core, "source_catalog", lambda kb: {})
    request = RetrievalRequest(run_id="r", step_id="s", knowledge_base_id="kb-fixture", queries=["q"],
        policy=RetrievalPolicy(top_k_per_query=3, ranking_strategy_version=VERSION))
    assert len(instance.retrieve(request).evidence) == 3
    old_backend = instance.backend
    instance.backend = SimpleNamespace(search=old_backend.search)
    fallback = instance.retrieve(request)
    assert len(fallback.evidence) == 3 and fallback.retrieval_profile["learning_candidate_window"] == "legacy_adapter"
    bad = old_backend.search(query="q", top_k=3, knowledge_base_id="kb-fixture")[0].model_copy(update={"query_rank": 21})
    instance.backend = SimpleNamespace(search=lambda **kw: [bad])
    assert instance.retrieve(request).status == RetrievalStatus.RETRIEVAL_ERROR


def test_configuration_fingerprint_changes_only_when_new_policy_is_selected():
    kwargs = {"retrieval_scope": "global", "knowledge_base_id": "kb-fixture"}
    enabled = Settings(_env_file=None, retrieval_balanced_candidates_enabled=False, learning_retrieval_refinement_enabled=True)
    disabled = enabled.model_copy(update={"learning_retrieval_refinement_enabled": False})
    old = RetrievalPolicy()
    assert retrieval_core._config_payload(enabled, old, **kwargs) == retrieval_core._config_payload(disabled, old, **kwargs)
    new = old.model_copy(update={"ranking_strategy_version": VERSION})
    assert retrieval_core._config_payload(enabled, new, source_catalog_fingerprint="a", **kwargs) != retrieval_core._config_payload(enabled, new, source_catalog_fingerprint="b", **kwargs)
