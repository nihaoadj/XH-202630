import json

import pytest
from langchain_core.documents import Document
from pydantic import ValidationError

from app.agents.shared import retrieval
from app.agents.shared.recorded_node import RecordedNode
from app.config import Settings
from app.core.retrieval import vector_store, reranker
from app.core.retrieval.knowledge_ids import query_hash
from app.core.retrieval.retriever import EvidenceRetriever
from app.db.knowledge.memory import MemoryKnowledgeChunkRepository
from app.models.knowledge.knowledge import (
    EvidenceAllocation, QueryPurpose, RESOURCE_AWARE_STRATEGY, RetrievalPolicy,
    RetrievalRequest, RetrievalStatus,
)
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES as TYPES
from app.models.shared.persistence import build_checkpoint_projection
from app.models.shared.workflow import WorkflowStateSnapshot
from app.services.generation import generation
from app.services.runs.durable_workflow_runner import DurableWorkflowRunner
from tests.fakes.evidence import make_knowledge_chunk
from tests.fakes.persistence import create_command, memory_repository, sqlite_repository
from tests.fakes.llm import ScriptedLLMGateway


def chunk(name):
    return make_knowledge_chunk(chunk_id=name, text=f"冻结依据{name}")


def document(value):
    return Document(page_content=value.text, metadata={
        "knowledge_base_id": value.knowledge_base_id, "chunk_id": value.chunk_id,
        "document_id": value.document_id, "document_version": value.document_version,
        "text_hash": value.text_hash,
    })


def setup_retriever(monkeypatch, hits, *, rerank_failure=False, settings=None):
    calls = []

    def hybrid(query, **kwargs):
        calls.append(query)
        value = hits.get(query, [])
        if isinstance(value, Exception):
            raise value
        return [(document(item), score) for item, score in value]

    def rerank(queries, candidates, top_k, **kwargs):
        assert kwargs["candidate_limit"] == 20
        assert len(queries) == len(candidates) <= 20
        if rerank_failure:
            raise RuntimeError("offline reranker")
        return sorted(candidates, key=lambda value: -value[1])

    monkeypatch.setattr(vector_store, "hybrid_search", hybrid)
    monkeypatch.setattr(reranker, "rerank_documents", rerank)
    settings = settings or Settings(_env_file=None)
    backend = vector_store.ChromaVectorSearchBackend(settings)
    chunks = {item.chunk_id: item for values in hits.values() if not isinstance(values, Exception) for item, _ in values}
    retriever = EvidenceRetriever(backend=backend, chunk_repository=MemoryKnowledgeChunkRepository(chunks.values()), settings=settings)
    return retriever, backend, calls


def request(bindings, *, types=TYPES, count=8, top_k=3, **kwargs):
    return RetrievalRequest(run_id="run", step_id="step", knowledge_base_id="kb-fixture",
        queries=list(bindings), query_bindings=bindings, resource_types=list(types),
        policy=RetrievalPolicy(strategy_version=RESOURCE_AWARE_STRATEGY, max_query_count=10,
                               max_evidence_count=count, top_k_per_query=top_k), **kwargs)


@pytest.mark.parametrize("types", [[kind] for kind in TYPES] + [list(TYPES)])
def test_real_candidate_path_allocates_common_specific_and_freezes_once(monkeypatch, types):
    shared = chunk("shared")
    bindings = {"public": [QueryPurpose(node_id="n1")]}
    hits = {"public": [(shared, .95)]}
    for kind in types:
        bindings[kind] = [QueryPurpose(node_id="n1", resource_type=kind)]
        hits[kind] = [(shared, .9), (chunk(kind), .8)]
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    result = retriever.retrieve(request(bindings, types=types))
    assert result.status == RetrievalStatus.AVAILABLE
    assert len({item.chunk_id for item in result.evidence}) == len(result.evidence) == len(types) + 1
    allocation = result.evidence_allocation
    common_id = next(item.evidence_id for item in result.evidence if item.chunk_id == "shared")
    assert allocation.common_evidence_ids == [common_id]
    for kind in types:
        own_id = next(item.evidence_id for item in result.evidence if item.chunk_id == kind)
        assert set(allocation.available_ids(kind)) == {common_id, own_id}
        assert common_id in allocation.resource_specific_evidence_ids[kind]
    assert len(allocation.evidence_query_hashes[common_id]) == len(types) + 1
    assert result.node_evidence_map["n1"] == [item.evidence_id for item in result.evidence]
    assert result.retrieval_profile["evidence_allocation"] == allocation.model_dump(mode="json")


@pytest.mark.parametrize("rerank_failure", [False, True])
def test_owner_score_rank_and_late_overlap_survive_full_pool(monkeypatch, rerank_failure):
    bindings = {}
    hits = {}
    for index in range(10):
        query = f"q{index}"
        bindings[query] = [QueryPurpose(node_id=f"n{index % 2}", resource_type=None if index < 2 else TYPES[(index - 2) % 5])]
        hits[query] = [(chunk(f"{query}-{rank}"), .99 - index * .01 - rank * .001) for rank in range(8)]
    overlap = hits["q0"][0][0]
    hits["q9"].append((overlap, .999))
    retriever, backend, _ = setup_retriever(monkeypatch, hits, rerank_failure=rerank_failure)
    candidates = backend.search_many(queries=list(bindings), top_k=3, knowledge_base_id="kb-fixture", query_bindings=bindings)
    assert len(candidates) == 20
    assert len({item.chunk_id for item in candidates}) == 20
    owners = {}
    for item in candidates:
        owners.setdefault(item.query, []).append(item.query_rank)
        expected_score = next(score for value, score in hits[item.query] if value.chunk_id == item.chunk_id)
        assert (item.raw_score + 1) / 2 == pytest.approx(expected_score)
    assert all(sorted(ranks) == list(range(1, len(ranks) + 1)) and len(ranks) <= 3 for ranks in owners.values())
    selected_overlap = next(item for item in candidates if item.chunk_id == overlap.chunk_id)
    assert selected_overlap.query == "q0"  # node reservation owns the lower-scoring hit
    assert selected_overlap.matched_queries == ["q0", "q9"]
    result = retriever.retrieve(request(bindings, count=2))
    allocation = result.evidence_allocation
    overlap_id = next(item.evidence_id for item in result.evidence if item.chunk_id == overlap.chunk_id)
    assert overlap_id in allocation.resource_specific_evidence_ids[TYPES[2]]
    assert overlap_id in result.node_evidence_map["n1"]


def test_four_queries_top_k_three_cannot_inflate_to_twenty(monkeypatch):
    bindings = {f"q{i}": [QueryPurpose(resource_type=TYPES[i])] for i in range(4)}
    hits = {query: [(chunk(f"{query}-{j}"), .9) for j in range(10)] for query in bindings}
    _, backend, _ = setup_retriever(monkeypatch, hits)
    result = backend.search_many(queries=list(bindings), top_k=3, knowledge_base_id="kb-fixture", query_bindings=bindings)
    assert len(result) == 12


def test_real_reranker_diversity_does_not_change_owner_score_order(monkeypatch):
    settings = Settings(_env_file=None, rerank_max_chunks_per_document=1,
                        rerank_candidate_k=1, retrieval_dense_reserve=0)
    chunks = [chunk(str(i)) for i in range(3)]
    docs = [document(item) for item in chunks]
    docs[2].metadata["document_id"] = "another-doc"
    monkeypatch.setattr(vector_store, "hybrid_search", lambda *args, **kwargs: [(doc, .9) for doc in docs])
    monkeypatch.setattr(reranker, "get_settings", lambda: settings)

    class Model:
        def predict(self, pairs, **kwargs):
            assert len(pairs) == 3  # E1 fixed limit overrides legacy candidate_k.
            return [4., 3., 1.]

    monkeypatch.setattr(reranker, "get_reranker", lambda: Model())
    backend = vector_store.ChromaVectorSearchBackend(settings)
    result = backend.search_many(queries=["p"], top_k=3, knowledge_base_id="kb-fixture",
                                 query_bindings={"p": [QueryPurpose()]})
    assert [item.chunk_id for item in result] == ["0", "1", "2"]
    assert [item.query_rank for item in result] == [1, 2, 3]
    assert [item.raw_score for item in result] == sorted([item.raw_score for item in result], reverse=True)


def test_resource_allocation_preserves_verified_language_preference_and_raw_scores(monkeypatch):
    import math

    english = make_knowledge_chunk(chunk_id="en", text="English source", source_path="references/en/real.md")
    chinese = make_knowledge_chunk(chunk_id="zh", text="中文来源", source_path="references/zh/real.md")
    scores = {english.text: .70, chinese.text: .74}
    settings = Settings(_env_file=None, retrieval_balanced_candidates_enabled=False,
                        retrieval_english_score_bonus=.08)
    original_rerank = reranker.rerank_documents
    retriever, backend, _ = setup_retriever(monkeypatch, {"public": [(chinese, .9), (english, .8)]}, settings=settings)

    class Model:
        def predict(self, pairs, **kwargs):
            return [math.log(scores[text] / (1 - scores[text])) for _, text in pairs]

    monkeypatch.setattr(reranker, "rerank_documents", original_rerank)
    monkeypatch.setattr(reranker, "get_settings", lambda: settings)
    monkeypatch.setattr(reranker, "get_reranker", lambda: Model())
    bindings = {"public": [QueryPurpose(node_id="n1")]}
    result = retriever.retrieve(request(bindings, count=1, top_k=2))
    assert result.status == RetrievalStatus.AVAILABLE
    assert result.evidence[0].chunk_id == "en"
    assert result.evidence[0].normalized_score == pytest.approx(.70)
    assert result.evidence_allocation.common_evidence_ids == [result.evidence[0].evidence_id]
    assert result.node_evidence_map["n1"] == [result.evidence[0].evidence_id]
    assert backend.last_profile["source_validation_count"] == 2


def test_fallback_alias_match_cannot_grant_resource_purpose(monkeypatch):
    from app.core.retrieval import query_expansion

    shared = chunk("shared")
    bindings = {"public": [QueryPurpose()], "specific": [QueryPurpose(resource_type=TYPES[0])]}
    hits = {"public": [(shared, .9)], "specific": [], "alias-probe": [(shared, .95)]}
    retriever, _, _ = setup_retriever(monkeypatch, hits, rerank_failure=True)
    monkeypatch.setattr(query_expansion, "expand_query", lambda query, kb:
                        (["alias-probe"] if query == "specific" else [], {}))
    result = retriever.retrieve(request(bindings, types=[TYPES[0]]))
    assert result.status == RetrievalStatus.AVAILABLE
    assert len(result.evidence) == 1
    assert result.evidence[0].query == "public"
    assert result.evidence_allocation.resource_specific_evidence_ids[TYPES[0]] == []


def test_content_redundancy_preserves_distinct_resource_purposes(monkeypatch):
    text = ("Frozen source evidence remains bound to its actual query and resource purpose. " * 4).strip()
    public = make_knowledge_chunk(chunk_id="public", text=text)
    duplicate = make_knowledge_chunk(chunk_id="duplicate", document_id="other", document_version="v-other", text=text)
    specific = make_knowledge_chunk(chunk_id="specific", document_id="specific", document_version="v-specific", text=text)
    bindings = {"p": [QueryPurpose(node_id="n1")],
                "s": [QueryPurpose(node_id="n1", resource_type=TYPES[0])]}
    hits = {"p": [(public, .9), (duplicate, .8)], "s": [(specific, .7)]}
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    result = retriever.retrieve(request(bindings, types=[TYPES[0]]))
    assert {item.chunk_id for item in result.evidence} == {"public", "specific"}
    assert result.retrieval_profile["redundancy"]["dropped_count"] == 1
    assert result.retrieval_profile["redundancy"]["coverage_protected_count"] == 1
    allocation = result.evidence_allocation
    by_chunk = {item.chunk_id: item.evidence_id for item in result.evidence}
    assert allocation.common_evidence_ids == [by_chunk["public"]]
    assert allocation.resource_specific_evidence_ids[TYPES[0]] == [by_chunk["specific"]]


def test_common_then_type_opportunities_precede_extra_public_evidence(monkeypatch):
    bindings = {"public": [QueryPurpose()]}
    hits = {"public": [(chunk(f"public{index}"), .99 - index * .01) for index in range(3)]}
    for kind in TYPES:
        bindings[kind] = [QueryPurpose(resource_type=kind)]
        hits[kind] = [(chunk(kind), .6)]
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    result = retriever.retrieve(request(bindings, count=6))
    assert {item.chunk_id for item in result.evidence} == {"public0", *TYPES}


def test_missing_public_promotes_node_evidence_without_borrowing_other_specific(monkeypatch):
    bindings = {"p1": [QueryPurpose(node_id="n1")], "p2": [QueryPurpose(node_id="n2")],
                "s": [QueryPurpose(node_id="n2", resource_type="实操指南")]}
    retriever, _, _ = setup_retriever(monkeypatch, {"p1": [(chunk("c"), .9)], "s": [(chunk("s"), .8)]})
    result = retriever.retrieve(request(bindings, types=["讲义", "实操指南"]))
    assert len(result.evidence_allocation.common_evidence_ids) == 2
    assert any(gap["reason"] == "common_promoted_from_specific" for gap in result.evidence_allocation.gaps)
    assert result.evidence_allocation.resource_specific_evidence_ids["讲义"] == []


def test_specific_no_hit_filter_budget_and_partial_failure_are_distinct(monkeypatch):
    bindings = {"p": [QueryPurpose()], "empty": [QueryPurpose(resource_type="讲义")],
                "low": [QueryPurpose(resource_type="实操指南")],
                "omitted": [QueryPurpose(resource_type="分阶测试题")],
                "failed": [QueryPurpose(resource_type="复习清单")]}
    hits = {"p": [(chunk("c"), .9)], "low": [(chunk("low"), .1)],
            "omitted": [(chunk("s"), .8)], "failed": RuntimeError("unavailable")}
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    result = retriever.retrieve(request(bindings, count=1))
    assert result.partial_failure_count == 1
    reasons = {gap.get("query_hash"): gap["reason"] for gap in result.evidence_allocation.gaps}
    assert reasons[query_hash("empty")] == "query_no_hit"
    assert reasons[query_hash("low")] == "candidate_filtered"
    assert reasons[query_hash("omitted")] == "evidence_not_selected"
    assert reasons[query_hash("failed")] == "query_failed"


def test_invalid_provenance_keeps_hard_failure(monkeypatch):
    source = chunk("bad")
    retriever, _, _ = setup_retriever(monkeypatch, {"p": [(source, .9)]})
    retriever.chunk_repository = MemoryKnowledgeChunkRepository([])
    result = retriever.retrieve(request({"p": [QueryPurpose()]}))
    assert result.status == RetrievalStatus.RETRIEVAL_ERROR
    assert result.evidence_allocation is None and not result.evidence


def test_configuration_hash_covers_effective_rerank_and_strategy(monkeypatch):
    bindings = {"p": [QueryPurpose()]}
    hits = {"p": [(chunk("c"), .9)]}
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    first = retriever.retrieve(request(bindings))
    retriever.settings = retriever.settings.model_copy(update={"rerank_max_length": 256})
    second = retriever.retrieve(request(bindings))
    assert first.config_hash != second.config_hash
    with pytest.raises(ValidationError):
        EvidenceAllocation.model_validate({**first.evidence_allocation.model_dump(), "step_id": "another-step"})


@pytest.mark.parametrize("scoped_no_hit", [False, True])
def test_node_scope_fallback_selects_one_global_batch(monkeypatch, scoped_no_hit):
    monkeypatch.setattr(retrieval, "_node_descriptor", lambda node: (node, []))
    inputs = retrieval.RetrieverInput(topic="主题", knowledge_base_id="kb-fixture", resource_types=["讲义"], target_skill_nodes=["n"],
                                      retrieval_strategy_version=RESOURCE_AWARE_STRATEGY)
    queries = retrieval._resource_queries(inputs, 10)[0]
    hits = {query: [(chunk(f"{i}"), .9)] for i, query in enumerate(queries)}
    retriever, _, _ = setup_retriever(monkeypatch, hits)
    monkeypatch.setattr(retriever, "get_active_chunk_ids_for_skill_nodes", lambda *args: ["missing"])
    hybrid = vector_store.hybrid_search
    if scoped_no_hit:
        monkeypatch.setattr(vector_store, "hybrid_search", lambda query, **kwargs:
                            [] if kwargs.get("allowed_chunk_ids") else hybrid(query, **kwargs))
    final = retrieval.retrieve_node(inputs.model_dump(), evidence_retriever=retriever)
    assert final["retrieval_profile"]["final_retrieval_source"] == "global_fallback"
    # The adapter now rejects out-of-scope IDs before reranking as well as
    # retaining the retriever's final SQL defense. Both cases have no hits.
    assert final["retrieval_profile"]["node_scope_fallback_reason"] == "no_hit"
    allocation = final["evidence_allocation"]
    assert allocation.evidence_ids == [item.evidence_id for item in final["retrieved_evidence"]]
    assert allocation.config_hash == final["retrieval_config_hash"]


@pytest.mark.parametrize("types", [[kind] for kind in TYPES] + [list(TYPES)])
def test_compiled_e1_workflow_preserves_fallback_and_draft_routes(monkeypatch, types):
    from app.agents.resource_workflows.learning_documents import workflow, planner_agent, generator_agent
    from app.core.security import errors
    from app.core.security.errors import ErrorCode
    from app.core.llm.gateway import LLMGatewayError
    from app.models.shared.agent_contracts import make_error_info

    settings = Settings(_env_file=None, app_mode="demo", allow_degraded_generation=True,
        resource_aware_retrieval_enabled=True, resource_worker_max_concurrency=1,
        resource_aware_planner_context_tokens=100000, resource_aware_planner_input_budget_tokens=90000)
    for module in [generation, planner_agent, generator_agent, errors]:
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(retrieval, "_node_descriptor", lambda node: (node, []))
    learner = LearnerProfile(learner_id="e1-full", learner_type="初学者", education="本科", major="计算机", learning_goal="学习")
    req = GenerateRequest(learner_id=learner.learner_id, topic="主题", knowledge_base_id="kb-fixture",
                          resource_types=types, target_skill_nodes=["n1", "n2"], include_review=False)
    initial = generation.build_workflow_state(learner, req)
    queries = retrieval._resource_queries(retrieval.RetrieverInput.model_validate(initial), 10)[0]
    common = chunk("common")
    # Shared overlap gives every explicitly requested node a valid mapping.
    hits = {query: [(common, .95), (chunk(f"own{i}"), .8)] for i, query in enumerate(queries)}
    retriever, _, _ = setup_retriever(monkeypatch, hits, settings=settings)
    failure = LLMGatewayError(error=make_error_info(ErrorCode.LLM_TIMEOUT, source="fixture", category="llm"),
                              call_id="offline", retry_count=0, latency_ms=0, attempts=[])
    gateway = ScriptedLLMGateway([failure] * 30)
    final = workflow.build_workflow(llm_gateway=gateway, evidence_retriever=retriever).invoke(initial)
    assert [item["agent_name"] for item in final["trace"]] == ["diagnosis", "retriever", "evidence_gate", "planner", "generator", "supervisor"]
    assert len(final["generated_resources"]) == len(types)
    assert all(resource.publication_status == "unpublished" for resource in final["generated_resources"])
    allocation = EvidenceAllocation.model_validate(final["evidence_allocation"])
    for resource in final["generated_resources"]:
        spec = next(spec for spec in final["resource_specs"] if spec["resource_spec_id"] == resource.resource_spec_id)
        assert spec["evidence_ids"] == allocation.available_ids(resource.resource_type)
        assert {ref.evidence_id for ref in resource.source_refs} <= set(spec["evidence_ids"])
    assert final["retrieval_strategy_version"] == RESOURCE_AWARE_STRATEGY


@pytest.mark.parametrize("storage", ["memory", "sqlite"])
def test_recording_and_checkpoint_roundtrip_preserve_one_allocation(monkeypatch, tmp_path, storage):
    monkeypatch.setattr(retrieval, "_node_descriptor", lambda node: (node, []))
    settings = Settings(_env_file=None, resource_aware_retrieval_enabled=True)
    monkeypatch.setattr(generation, "get_settings", lambda: settings)
    learner = LearnerProfile(learner_id="learner-001", learner_type="初学者", education="本科", major="计算机", learning_goal="学习")
    req = GenerateRequest(learner_id=learner.learner_id, topic="主题", knowledge_base_id="kb-fixture", resource_types=list(TYPES),
                          target_skill_nodes=["n1", "n2"])
    state = generation.build_workflow_state(learner, req, run_id="run")
    snapshot = generation._request_snapshot(req, state)
    assert snapshot["retrieval_strategy_version"] == RESOURCE_AWARE_STRATEGY
    inputs = retrieval.RetrieverInput.model_validate(state)
    queries = retrieval._resource_queries(inputs, 10)[0]
    hits = {query: [(chunk(f"c{i}"), .9)] for i, query in enumerate(queries)}
    retriever, _, _ = setup_retriever(monkeypatch, hits, settings=settings)
    repository = memory_repository() if storage == "memory" else sqlite_repository(tmp_path)[0]
    command = create_command("run", knowledge_base_id="kb-fixture")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    recorded = RecordedNode("retrieve", lambda current: retrieval.retrieve_node(current, evidence_retriever=retriever), repository)

    class Workflow:
        def stream(self, initial, stream_mode=None):
            yield {**initial, **recorded(initial)}

    final = DurableWorkflowRunner(Workflow(), repository).invoke(state)
    allocation = final["evidence_allocation"].model_dump(mode="json")
    checkpoint = repository.list_checkpoints("run")[0].state_projection
    # Persistence strips optional null fields; validated ID/assignment/hash
    # contracts round-trip unchanged after those defaults are restored.
    assert EvidenceAllocation.model_validate(checkpoint["evidence_allocation"]).model_dump(mode="json") == allocation
    assert EvidenceAllocation.model_validate(repository.list_steps("run")[0].retrieval_profile["evidence_allocation"]).model_dump(mode="json") == allocation
    assert len(repository.list_evidence("run")) == len(final["retrieved_evidence"])
    assert checkpoint["node_evidence_map"] == final["node_evidence_map"]
    assert set(checkpoint["node_evidence_map"]) == {"n1", "n2"}
    serialized = json.dumps(checkpoint, ensure_ascii=False)
    assert len(serialized.encode("utf-8")) < 65536
    assert "冻结依据" not in serialized
    assert WorkflowStateSnapshot.model_validate(final).evidence_allocation.model_dump(mode="json") == allocation
    settings.resource_aware_retrieval_enabled = False
    assert generation.build_workflow_state(learner, req)["retrieval_strategy_version"] == "legacy"
    assert EvidenceAllocation.model_validate(build_checkpoint_projection(final)["evidence_allocation"]).model_dump(mode="json") == allocation
