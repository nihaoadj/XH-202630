import pytest
from pydantic import ValidationError

from app.agents.shared import retrieval
from app.agents.shared.retrieval import _resource_queries, retrieve_node
from app.config import Settings
from app.models.knowledge.knowledge import RESOURCE_AWARE_STRATEGY
from app.models.learning_documents.schemas import GenerateRequest
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES as TYPES
from app.models.shared.agent_contracts import RetrieverInput
from tests.fakes.evidence import ScriptedEvidenceRetriever, make_available_batch, make_evidence


def node_input(nodes=None, types=TYPES, topic="主题"):
    return RetrieverInput(topic=topic, resource_types=list(types), target_skill_nodes=nodes or [],
                          retrieval_strategy_version=RESOURCE_AWARE_STRATEGY)


@pytest.fixture(autouse=True)
def descriptors(monkeypatch):
    monkeypatch.setattr(retrieval, "_node_descriptor", lambda node: (f"名称{node}", [f"要点{node}"]))


@pytest.mark.parametrize("nodes", [[], ["n1"], ["n1", "n2"], ["n1", "n2", "n3"]])
@pytest.mark.parametrize("count", [1, 2, 5])
def test_query_schedule_is_stable_bounded_and_preserves_public(nodes, count):
    value = node_input(nodes, TYPES[:count])
    result = _resource_queries(value, 10)
    assert result == _resource_queries(value, 10)
    queries, _, bindings, types, gaps = result
    assert len(queries) <= 10
    assert queries[:len(nodes) + 1] == retrieval._queries(value)[0]
    assert list(bindings) == queries and types == list(TYPES[:count])
    assert all(len(query) <= 2000 for query in queries)
    if len(nodes) == 2 and count == 5:
        first = {kind: next(p.node_id for values in bindings.values() for p in values if p.resource_type == kind) for kind in types}
        assert list(first.values()) == ["n1", "n2", "n1", "n2", "n1"]
        assert len(gaps) == 3


def test_low_budget_does_not_discard_public_queries():
    assert _resource_queries(node_input(["n1", "n2"]), 2) is None
    result = _resource_queries(node_input(["n1", "n2"]), 3)
    assert len(result[0]) == 3
    assert {gap["reason"] for gap in result[-1]} == {"query_budget"}


def test_overlong_specific_queries_are_skipped_without_truncation():
    result = _resource_queries(node_input(topic="主" * 1998), 10)
    assert result[0] == ["主" * 1998]
    assert len(result[-1]) == 5
    assert {gap["reason"] for gap in result[-1]} == {"query_too_long"}


def test_normalized_duplicate_queries_merge_all_node_purposes(monkeypatch):
    monkeypatch.setattr(retrieval, "_node_descriptor", lambda node: ("同名", []))
    result = _resource_queries(node_input(["n1", "n2"]), 10)
    bindings = result[2]
    assert {p.node_id for p in bindings["主题 同名"] if p.node_id} == {"n1", "n2"}
    for values in bindings.values():
        if any(p.resource_type for p in values):
            assert {p.node_id for p in values} == {"n1", "n2"}


def test_low_budget_node_reports_actual_legacy_policy():
    fake = ScriptedEvidenceRetriever([make_available_batch([make_evidence()])],
        settings=Settings(_env_file=None, resource_aware_retrieval_max_queries=1))
    state = node_input(["n1", "n2"]).model_dump()
    result = retrieve_node(state, evidence_retriever=fake)
    assert result["retrieval_strategy_version"] == "legacy"
    assert result["retrieval_profile"]["strategy_fallback_reason"] == "query_budget_below_public_count"
    assert fake.calls[0].policy.max_query_count == 6


@pytest.mark.parametrize("types", [[], ["个性化纠错训练包"], ["个性化纠错训练包", "分阶测试题"]])
def test_shared_internal_calls_remain_legacy(types):
    fake = ScriptedEvidenceRetriever([make_available_batch([make_evidence()])])
    result = retrieve_node(node_input(types=types).model_dump(), evidence_retriever=fake)
    assert result["retrieval_strategy_version"] == "legacy"
    assert fake.calls[0].policy.max_query_count == 6


def test_public_request_still_rejects_three_nodes():
    with pytest.raises(ValidationError):
        GenerateRequest(learner_id="learner", topic="主题", resource_types=["讲义"], target_skill_nodes=["n1", "n2", "n3"])
