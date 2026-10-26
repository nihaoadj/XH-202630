"""Offline E1 downstream boundaries against real node entry points."""
from types import SimpleNamespace

import pytest

from app.agents.shared.evidence_scope import evidence_for_resource, validate_payload_evidence
from app.agents.resource_workflows.learning_documents import generator_agent, planner_agent
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.core.security.errors import ApplicationError
from app.models.knowledge.knowledge import EvidenceAllocation, retrieval_config_hash
from app.models.learning_documents.schemas import LearnerProfile
from app.models.shared.agent_contracts import GeneratorInput
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def state_fixture(count=3):
    evidence = [make_evidence(evidence_id=f"ev-{i}", chunk_id=f"chunk-{i}", excerpt=f"unique-{i}-" + "长" * 170 + f"tail-{i}") for i in range(count)]
    bindings = {evidence[0].query_hash: [{"node_id": "node", "resource_type": None}]}
    data = dict(strategy_version="resource-aware-v1", step_id="retrieve-step", config_hash="2" * 64,
                resource_types=["讲义", "案例分析"], evidence_ids=[item.evidence_id for item in evidence],
                common_evidence_ids=["ev-0"], resource_specific_evidence_ids={"讲义": [item.evidence_id for item in evidence[1:-1]], "案例分析": [evidence[-1].evidence_id]},
                query_bindings=bindings, evidence_query_hashes={item.evidence_id: [item.query_hash] for item in evidence},
                gaps=[{"resource_type": "讲义", "reason": "fixture-gap"}], binding_hash=retrieval_config_hash(bindings))
    data["allocation_hash"] = retrieval_config_hash(data)
    allocation = EvidenceAllocation.model_validate(data)
    learner = LearnerProfile(learner_id="e1-learner", learner_type="初学者", education="本科", major="计算机", theory_scores={}, skill_level="初级", weak_points=[], strong_points=[], learning_goal="学习")
    return dict(run_id="e1-run", batch_id="e1-run", learner=learner, topic="检索", resource_types=data["resource_types"],
                retrieved_evidence=evidence, evidence_allocation=allocation, retrieval_strategy_version="resource-aware-v1",
                retrieval_config_hash="2" * 64, target_skill_nodes=["node"], node_evidence_map={"node": data["evidence_ids"]},
                learning_plan={}, diagnosis={}, trace=[], generation_attempt=1)


def specs_for(state):
    return build_resource_specs(run_id=state["run_id"], resource_types=state["resource_types"], topic=state["topic"], difficulty="初级", learning_plan={}, evidence=state["retrieved_evidence"], target_skill_nodes=state["target_skill_nodes"], node_evidence_map=state["node_evidence_map"], evidence_allocation=state["evidence_allocation"])


def test_spec_context_and_fallback_share_the_same_boundary():
    state = state_fixture()
    specs = specs_for(state)
    assert specs[0].evidence_ids == ["ev-0", "ev-1"]
    assert specs[1].evidence_ids == ["ev-0", "ev-2"]
    assert specs[0].node_evidence_map == {"node": ["ev-0", "ev-1"]}
    state["resource_specs"] = [item.model_dump(mode="json") for item in specs]
    node_input = GeneratorInput.model_validate(state)
    context = generator_agent._context(node_input, state, "worker", spec=specs[0])
    assert [item.evidence_id for item in context.evidence] == specs[0].evidence_ids
    resource = generator_agent._fallback(specs[0], node_input, None)
    assert [item.evidence_id for item in resource.source_refs] == ["ev-0", "ev-1"]
    assert [item.evidence_id for item in evidence_for_resource(state, resource)] == specs[0].evidence_ids
    validate_payload_evidence(SimpleNamespace(practice_guide_payload={"steps": [{"evidence_ids": ["ev-1"]}]}), context.evidence)
    with pytest.raises(ApplicationError):
        validate_payload_evidence(SimpleNamespace(practice_guide_payload={"steps": [{"evidence_ids": ["ev-2"]}]}), context.evidence)


@pytest.mark.parametrize("damage", ["allocation", "spec", "config", "map"])
def test_e1_corrupt_boundary_fails_closed(damage):
    state = state_fixture()
    specs = specs_for(state)
    state["resource_specs"] = [item.model_dump(mode="json") for item in specs]
    if damage == "allocation":
        state["evidence_allocation"] = None
    elif damage == "spec":
        state["resource_specs"][0]["evidence_ids"] = ["ev-0", "ev-2"]
        state["resource_specs"][0]["node_evidence_map"] = {"node": ["ev-0", "ev-2"]}
    elif damage == "config":
        state["retrieval_config_hash"] = "3" * 64
    else:
        state["resource_specs"][0]["node_evidence_map"] = {}
    resource = generator_agent._fallback(specs[0], GeneratorInput.model_validate(state), None)
    with pytest.raises(ApplicationError):
        evidence_for_resource(state, resource)


def test_revision_cannot_rebuild_missing_e1_spec():
    state = state_fixture()
    state["generation_attempt"] = 2
    with pytest.raises(ApplicationError):
        generator_agent._specs_for_state(state, GeneratorInput.model_validate(state))


def test_legacy_spec_keeps_original_ids():
    state = state_fixture()
    specs = specs_for(state)
    state["retrieval_strategy_version"] = "legacy"
    state["resource_specs"] = [item.model_dump(mode="json") for item in specs]
    resource = generator_agent._fallback(specs[0], GeneratorInput.model_validate(state), None)
    assert [item.evidence_id for item in evidence_for_resource(state, resource)] == ["ev-0", "ev-1"]
    state.pop("resource_specs")
    assert len(evidence_for_resource(state, resource)) == 3


def planner_result():
    return dict(learning_path=[{"order": 1, "topic": "node", "reason": "范围"}], skip_points=[], remedial_points=[], challenge_points=[], resource_requirements={"讲义": "讲义要求", "案例分析": "案例要求", "实操指南": "未选要求"}, decision_reason="证据规划")


def test_planner_sees_complete_unique_evidence_and_selected_types(monkeypatch):
    state = state_fixture(8)
    monkeypatch.setattr(planner_agent, "get_settings", lambda: SimpleNamespace(resource_aware_planner_context_tokens=100000, resource_aware_planner_input_budget_tokens=90000))
    gateway = ScriptedLLMGateway([planner_result()])
    result = planner_agent.plan_node(state, llm_gateway=gateway)
    prompt = gateway.calls[0]["messages"][1].content
    for i in range(8):
        assert prompt.count(f"unique-{i}-") == 1
        assert f"tail-{i}" in prompt
    assert "fixture-gap" in prompt and "source.md" in prompt and "node_evidence_map" in prompt
    assert set(result["learning_plan"]["resource_requirements"]) == {"讲义", "案例分析"}
    assert result["trace"][0]["evidence_refs"] == [f"ev-{i}" for i in range(8)]


@pytest.mark.parametrize("window,budget", [(None, 32768), (200000, 1), (1, 32768)])
def test_planner_budget_strict_fails_before_model(monkeypatch, window, budget):
    state = state_fixture()
    state["generation_mode"] = "strict"
    monkeypatch.setattr(planner_agent, "get_settings", lambda: SimpleNamespace(resource_aware_planner_context_tokens=window, resource_aware_planner_input_budget_tokens=budget))
    gateway = ScriptedLLMGateway([])
    with pytest.raises(ApplicationError):
        planner_agent.plan_node(state, llm_gateway=gateway)
    assert not gateway.calls


def claim_state():
    from app.models.learning_documents.schemas import LearningResource
    from app.core.retrieval.evidence import source_refs_from_evidence
    state = state_fixture()
    specs = specs_for(state)
    state["resource_specs"] = [item.model_dump(mode="json") for item in specs]
    resource = LearningResource(resource_id="e1-resource", resource_spec_id=specs[0].resource_spec_id,
        resource_family_id=specs[0].resource_family_id, resource_type="讲义", difficulty="初级",
        content_text="冻结证据限制可用事实。", knowledge_points=["node"],
        source_refs=source_refs_from_evidence(state["retrieved_evidence"][:2]), run_id=state["run_id"], version=1)
    state["generated_resources"] = [resource]
    state["review_result"] = {"decision": "approve", "review_ids": {resource.resource_id: "review-e1"}}
    return state, resource


def test_unrequested_spec_type_uses_contract_error():
    state, resource = claim_state()
    state["resource_specs"][0]["resource_type"] = "实操指南"
    resource.resource_type = "实操指南"
    with pytest.raises(ApplicationError) as caught:
        evidence_for_resource(state, resource)
    assert caught.value.code.value == "WORKFLOW_CONTRACT_INVALID"
    assert caught.value.status_code == 422


def extraction(resource, evidence_id):
    content = resource.content_text
    return {"resources": [{"resource_id": resource.resource_id, "claims": [{
        "claim_text": content, "claim_type": "factual", "source_text": content,
        "source_start": 0, "source_end": len(content), "knowledge_point_id": "node",
        "source_evidence_ids": [evidence_id]}]}]}


@pytest.mark.parametrize("evidence_id,failed", [("ev-1", False), ("ev-2", True)])
def test_claim_extractor_input_and_server_whitelist_match(evidence_id, failed):
    import json
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node
    state, resource = claim_state()
    gateway = ScriptedLLMGateway([extraction(resource, evidence_id)])
    result = claim_extract_node(state, llm_gateway=gateway)
    payload = json.loads(gateway.calls[0]["messages"][1].content)
    assert [item["evidence_id"] for item in payload["allowed_evidence"]] == ["ev-0", "ev-1"]
    assert (result.get("claim_check_status") == "failed" or bool(result.get("claim_failed_resource_ids"))) == failed


@pytest.mark.parametrize("evidence_id,failed", [("ev-1", False), ("ev-2", True)])
def test_claim_judge_input_and_server_whitelist_match(evidence_id, failed):
    import json
    from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node, claim_judge_node
    state, resource = claim_state()
    state.update(claim_extract_node(state, llm_gateway=ScriptedLLMGateway([extraction(resource, "ev-1")])))
    claim_id = state["extracted_claims"][0]["claim_id"]
    gateway = ScriptedLLMGateway([{"judgements": [{"claim_id": claim_id, "verdict": "supported", "evidence_ids": [evidence_id], "reason": "证据支持", "confidence": 0.9}]}])
    result = claim_judge_node(state, llm_gateway=gateway)
    payload = json.loads(gateway.calls[0]["messages"][1].content)
    assert [item["evidence_id"] for item in payload["allowed_evidence"]] == ["ev-0", "ev-1"]
    assert (result.get("claim_check_status") == "failed" or bool(result.get("claim_failed_resource_ids"))) == failed


def test_reviewer_receives_only_resource_spec_evidence():
    from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
    state, _ = claim_state()
    gateway = ScriptedLLMGateway([{"decision": "approve", "hallucination_score": 0.0, "issues": [], "difficulty_match": True, "coverage_rate": 1.0, "suggestion": "符合", "revision_instructions": []}])
    review_node(state, llm_gateway=gateway)
    prompt = gateway.calls[0]["messages"][1].content
    assert "unique-1-" in prompt and "unique-2-" not in prompt


def test_reviewer_rejects_another_resource_payload_evidence_before_model():
    from app.agents.resource_workflows.learning_documents.reviewer_agent import review_node
    state, resource = claim_state()
    state["generated_resources"] = [resource.model_copy(update={"practice_guide_payload": {"steps": [{"evidence_ids": ["ev-2"]}]}})]
    gateway = ScriptedLLMGateway([])
    with pytest.raises(ApplicationError):
        review_node(state, llm_gateway=gateway)
    assert not gateway.calls


def test_revision_reuses_frozen_spec_and_scope():
    state = state_fixture()
    specs = specs_for(state)
    frozen = [item.model_dump(mode="json") for item in specs]
    state.update(resource_specs=frozen, generation_attempt=2, revision_count=1)
    node_input = GeneratorInput.model_validate(state)
    restored = generator_agent._specs_for_state(state, node_input)
    assert [item.model_dump(mode="json") for item in restored] == frozen
    assert generator_agent._context(node_input, state, "revision-worker", spec=restored[0]).node_evidence_map == {"node": ["ev-0", "ev-1"]}


def test_unknown_strategy_fails_closed():
    state, resource = claim_state()
    state["retrieval_strategy_version"] = "future-unknown"
    with pytest.raises(ApplicationError):
        evidence_for_resource(state, resource)


def test_payload_model_is_checked_for_out_of_scope_ids():
    from pydantic import BaseModel
    class Payload(BaseModel):
        evidence_ids: list[str]
    state = state_fixture()
    with pytest.raises(ApplicationError):
        validate_payload_evidence(SimpleNamespace(practice_guide_payload=Payload(evidence_ids=["ev-2"])), state["retrieved_evidence"][:2])


def test_planner_budget_fallback_is_marked_and_scoped(monkeypatch):
    state = state_fixture()
    monkeypatch.setattr(planner_agent, "get_settings", lambda: SimpleNamespace(resource_aware_planner_context_tokens=None, resource_aware_planner_input_budget_tokens=32768))
    monkeypatch.setattr(planner_agent, "require_agent_fallback", lambda state, error: error)
    gateway = ScriptedLLMGateway([])
    result = planner_agent.plan_node(state, llm_gateway=gateway)
    assert not gateway.calls
    assert result["trace"][0]["status"] == "degraded"
    assert result["errors"][0]["category"] == "input_budget"
    assert "未执行 AI 规划" in result["learning_plan"]["decision_reason"]
    assert set(result["learning_plan"]["resource_requirements"]) == {"讲义", "案例分析"}
