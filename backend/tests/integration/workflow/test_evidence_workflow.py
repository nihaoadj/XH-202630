import pytest

from app.agents.resource_workflows.learning_documents import workflow as workflow_module
from app.models.shared.agent_contracts import build_trace_item
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.workflow import StepStatus
from app.services.generation.generation import build_workflow_state
from tests.fakes.evidence import make_evidence


def _learner():
    return LearnerProfile(
        learner_id="gate-user",
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="验证证据门禁",
    )


def _trace(state, name):
    return build_trace_item(
        state,
        agent_name=name,
        action=name,
        status=StepStatus.SUCCESS,
        input_summary="safe",
        output_summary="safe",
        decision_reason="test",
    )


def _invoke(monkeypatch, *, status, evidence, include_review=True):
    calls = {"plan": 0, "generate": 0, "review": 0}

    def diagnose(state):
        return {"diagnosis": {}, "trace": [_trace(state, "diagnosis")], "errors": []}

    def retrieve(state):
        return {
            "knowledge_base_id": "kb-gate",
            "retrieval_status": status,
            "retrieved_evidence": evidence,
            "retrieval_config_hash": "2" * 64,
            "retrieval_query_hashes": ["1" * 64],
            "retrieval_candidate_count": len(evidence),
            "retrieval_dropped_candidate_count": 0,
            "retrieval_partial_failure_count": 0,
            "trace": [_trace(state, "retriever")],
            "errors": [],
        }

    def plan(state):
        calls["plan"] += 1
        return {"learning_plan": {}, "trace": [_trace(state, "planner")], "errors": []}

    def generate(state):
        calls["generate"] += 1
        return {
            "generated_resources": [LearningResource(
                resource_id="resource-gate",
                resource_type="讲义",
                difficulty="初级",
                content_text="validated",
                knowledge_points=["gate"],
                source_refs=[],
            )],
            "trace": [_trace(state, "generator")],
            "errors": [],
        }

    def review(state):
        calls["review"] += 1
        return {
            "review_result": {
                "decision": "approve",
                "status": "approve",
                "passed": True,
                "hallucination_score": 0.0,
                "review_ids": {},
            },
            "trace": [_trace(state, "reviewer")],
            "errors": [],
        }

    monkeypatch.setattr(workflow_module, "diagnose_node", diagnose)
    monkeypatch.setattr(workflow_module, "retrieve_node", retrieve)
    monkeypatch.setattr(workflow_module, "plan_node", plan)
    monkeypatch.setattr(workflow_module, "generate_node", generate)
    monkeypatch.setattr(workflow_module, "review_node", review)
    request = GenerateRequest(
        learner_id="gate-user",
        topic="Evidence Gate",
        knowledge_base_id="kb-gate",
        resource_types=["讲义"],
        include_review=include_review,
    )
    result = workflow_module.build_workflow().invoke(
        build_workflow_state(_learner(), request, run_id="run-gate")
    )
    return result, calls


@pytest.mark.parametrize("retrieval_status", ["no_hit", "evidence_insufficient", "retrieval_error"])
@pytest.mark.parametrize("include_review", [True, False])
def test_evidence_gate_prevents_all_fact_generation_paths(
    monkeypatch,
    retrieval_status,
    include_review,
):
    result, calls = _invoke(
        monkeypatch,
        status=retrieval_status,
        evidence=[],
        include_review=include_review,
    )

    assert calls == {"plan": 0, "generate": 0, "review": 0}
    assert result["workflow_status"] == "human_review"
    assert result["generated_resources"] == []
    assert result["final_decision"] == "证据不足，未生成事实资源"
    assert "EVIDENCE_INSUFFICIENT" in {item["code"] for item in result["errors"]}


def test_available_valid_evidence_is_the_only_route_to_generation(monkeypatch):
    evidence = make_evidence(knowledge_base_id="kb-gate")
    result, calls = _invoke(
        monkeypatch,
        status="available",
        evidence=[evidence],
        include_review=True,
    )

    assert calls == {"plan": 1, "generate": 1, "review": 1}
    assert result["workflow_status"] == "completed"


def test_available_cross_kb_evidence_is_rejected_by_gate(monkeypatch):
    result, calls = _invoke(
        monkeypatch,
        status="available",
        evidence=[make_evidence(knowledge_base_id="other-kb")],
    )

    assert calls == {"plan": 0, "generate": 0, "review": 0}
    assert result["workflow_status"] == "human_review"
    assert result["generated_resources"] == []


def test_available_label_cannot_bypass_minimum_score(monkeypatch):
    result, calls = _invoke(
        monkeypatch,
        status="available",
        evidence=[make_evidence(
            knowledge_base_id="kb-gate",
            normalized_score=0.1,
        )],
    )

    assert calls == {"plan": 0, "generate": 0, "review": 0}
    assert result["workflow_status"] == "human_review"
