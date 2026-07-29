import json

import pytest

from app.agents import (
    diagnosis as diagnosis_module,
    generator as generator_module,
    planner as planner_module,
    retriever as retriever_module,
    reviewer as reviewer_module,
    workflow as workflow_module,
)
from app.models.agent_contracts import build_trace_item
from app.models.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.workflow import StepStatus
from app.services.generation_service import build_workflow_state


def _learner() -> LearnerProfile:
    return LearnerProfile(
        learner_id="flow-001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="测试工作流控制",
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


def _install_fake_nodes(monkeypatch, review_decision="approve"):
    calls = {"generate": 0, "review": 0}

    def diagnose(state):
        return {"diagnosis": {}, "trace": [_trace(state, "diagnosis")], "errors": []}

    def retrieve(state):
        return {
            "retrieved_chunks": [],
            "retrieval_status": "no_hit",
            "trace": [_trace(state, "retriever")],
            "errors": [],
        }

    def plan(state):
        return {"learning_plan": {}, "trace": [_trace(state, "planner")], "errors": []}

    def generate(state):
        calls["generate"] += 1
        attempt = state["generation_attempt"]
        previous = state.get("generated_resources", [])
        resource = LearningResource(
            resource_id=f"resource-{attempt}",
            resource_type="讲义",
            difficulty="初级",
            content_text=None,
            knowledge_points=["测试"],
            source_refs=[],
            version=attempt,
            parent_resource_id=previous[0].resource_id if previous else None,
        )
        return {
            "generated_resources": [resource],
            "iteration": attempt,
            "trace": [_trace(state, "generator")],
            "errors": [],
        }

    def review(state):
        calls["review"] += 1
        return {
            "review_result": {
                "decision": review_decision,
                "status": review_decision,
                "passed": review_decision == "approve",
                "hallucination_score": 0.0 if review_decision == "approve" else 0.5,
                "review_ids": {state["generated_resources"][0].resource_id: f"review-{calls['review']}"},
            },
            "trace": [_trace(state, "reviewer")],
            "errors": [],
        }

    monkeypatch.setattr(workflow_module, "diagnose_node", diagnose)
    monkeypatch.setattr(workflow_module, "retrieve_node", retrieve)
    monkeypatch.setattr(workflow_module, "plan_node", plan)
    monkeypatch.setattr(workflow_module, "generate_node", generate)
    monkeypatch.setattr(workflow_module, "review_node", review)
    return calls


def _invoke(monkeypatch, **request_overrides):
    calls = _install_fake_nodes(
        monkeypatch,
        review_decision=request_overrides.pop("review_decision", "approve"),
    )
    request = GenerateRequest(
        learner_id="flow-001",
        topic="控制流",
        resource_types=["讲义"],
        **request_overrides,
    )
    state = build_workflow_state(_learner(), request, run_id="run-flow")
    return workflow_module.build_workflow().invoke(state), calls


def test_include_review_false_skips_reviewer_and_returns_unreviewed_draft(monkeypatch):
    result, calls = _invoke(monkeypatch, include_review=False)

    assert calls == {"generate": 1, "review": 0}
    assert result["review_result"]["decision"] == "not_requested"
    assert result["generated_resources"][0].review_status == "unreviewed_draft"
    assert result["workflow_status"] == "completed"


@pytest.mark.parametrize("max_iterations", [0, 1, 2])
def test_max_iterations_counts_revisions_not_initial_generation(monkeypatch, max_iterations):
    result, calls = _invoke(
        monkeypatch,
        include_review=True,
        max_iterations=max_iterations,
        review_decision="revise",
    )

    expected_attempts = max_iterations + 1
    assert calls == {"generate": expected_attempts, "review": expected_attempts}
    assert result["generation_attempt"] == expected_attempts
    assert result["revision_count"] == max_iterations
    if max_iterations:
        assert result["generated_resources"][0].parent_resource_id == (
            f"resource-{expected_attempts - 1}"
        )
    assert result["workflow_status"] == "human_review"


def test_claim_check_request_is_explicitly_unavailable_before_p0_06(monkeypatch):
    result, calls = _invoke(
        monkeypatch,
        include_review=False,
        include_claim_check=True,
    )

    assert calls == {"generate": 1, "review": 0}
    assert result["claim_check_status"] == "unavailable"
    assert result["workflow_status"] == "human_review"
    assert result["generated_resources"][0].review_status == "unreviewed_draft"
    assert "CLAIM_CHECK_NOT_IMPLEMENTED" in [error["code"] for error in result["errors"]]


def test_review_approve_marks_resources_approved(monkeypatch):
    result, calls = _invoke(monkeypatch, include_review=True)

    assert calls == {"generate": 1, "review": 1}
    assert result["workflow_status"] == "completed"
    assert result["generated_resources"][0].review_status == "approved"


@pytest.mark.parametrize(
    ("decision", "workflow_status", "resource_status"),
    [
        ("reject", "failed", "rejected"),
        ("human_review", "human_review", "human_review"),
    ],
)
def test_terminal_review_decisions_are_not_approved(
    monkeypatch,
    decision,
    workflow_status,
    resource_status,
):
    result, calls = _invoke(
        monkeypatch,
        include_review=True,
        review_decision=decision,
    )

    assert calls == {"generate": 1, "review": 1}
    assert result["workflow_status"] == workflow_status
    assert result["generated_resources"][0].review_status == resource_status


def test_strict_mode_never_approves_degraded_output():
    resource = LearningResource(
        resource_id="strict-resource",
        resource_type="讲义",
        difficulty="高级",
        content_text=None,
        knowledge_points=["测试"],
        source_refs=[],
    )
    result = workflow_module.decide_node({
        "schema_version": "1.0",
        "run_id": "strict-run",
        "generation_mode": "strict",
        "generated_resources": [resource],
        "review_result": {"decision": "approve", "review_ids": {}},
        "revision_count": 0,
        "max_iterations": 1,
        "errors": [{"code": "LLM_UPSTREAM_UNAVAILABLE"}],
        "trace": [],
    })

    assert result["workflow_status"] == "human_review"
    assert result["generated_resources"][0].review_status == "human_review"


def test_real_agent_nodes_receive_request_controls_and_share_trace_ids(monkeypatch):
    captured = {}

    class Response:
        def __init__(self, payload):
            self.content = json.dumps(payload, ensure_ascii=False)

    class LLM:
        def __init__(self, name, payload):
            self.name = name
            self.payload = payload

        def invoke(self, messages):
            captured[self.name] = messages[-1].content
            return Response(self.payload)

    monkeypatch.setattr(
        diagnosis_module,
        "get_llm",
        lambda: LLM("diagnosis", {
            "ability_tags": [],
            "weak_points": [],
            "recommended_difficulty": "初级",
            "suggestion": "ok",
        }),
    )
    monkeypatch.setattr(
        planner_module,
        "get_llm",
        lambda: LLM("planner", {
            "learning_path": [],
            "resource_requirements": {},
            "decision_reason": "ok",
        }),
    )
    monkeypatch.setattr(
        generator_module,
        "get_llm",
        lambda: LLM("generator", [{
            "resource_type": "讲义",
            "difficulty": "初级",
            "content_text": "测试资源",
            "knowledge_points": ["node-a"],
        }]),
    )
    monkeypatch.setattr(
        reviewer_module,
        "get_llm",
        lambda: LLM("reviewer", {
            "passed": True,
            "hallucination_score": 0.0,
            "issues": [],
            "difficulty_match": True,
            "coverage_rate": 1.0,
            "suggestion": "ok",
        }),
    )
    retrieval_calls = []
    monkeypatch.setattr(
        retriever_module,
        "similarity_search",
        lambda query, top_k, knowledge_base_id: retrieval_calls.append(
            (query, top_k, knowledge_base_id)
        ) or [],
    )

    request = GenerateRequest(
        learner_id="flow-001",
        topic="控制流",
        knowledge_base_id="kb-contract",
        diagnostic_result_id="diag-contract",
        target_skill_nodes=["node-a"],
        resource_types=["讲义"],
        difficulty_preference="高级",
        generation_mode="standard",
        constraints={"retrieval_top_k": 4, "language": "zh-CN"},
    )
    result = workflow_module.build_workflow().invoke(
        build_workflow_state(_learner(), request, run_id="run-contract")
    )

    assert "diag-contract" in captured["diagnosis"]
    assert "node-a" in captured["diagnosis"]
    assert "zh-CN" in captured["planner"]
    assert "node-a" in captured["generator"]
    assert "高级" in captured["reviewer"]
    assert ("控制流 node-a", 4, "kb-contract") in retrieval_calls
    assert result["generated_resources"][0].difficulty == "高级"
    assert [item["sequence"] for item in result["trace"]] == list(
        range(1, len(result["trace"]) + 1)
    )
    assert {item["run_id"] for item in result["trace"]} == {"run-contract"}
