import json

import pytest

from app.agents.learning_agents import diagnosis_agent as diagnosis_module
from app.agents.resource_workflows.learning_documents import (
    generator_agent as generator_module,
    planner_agent as planner_module,
    reviewer_agent as reviewer_module,
    workflow as workflow_module,
)
from app.agents.shared import retrieval as retriever_module
from app.models.shared.agent_contracts import build_trace_item
from app.core.llm.gateway import LLMGateway
from app.models.shared.llm import RawLLMResponse
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.shared.workflow import StepStatus
from app.services.generation.generation import build_workflow_state
from tests.fakes.llm import ScriptedLLMTransport
from tests.fakes.evidence import (
    ScriptedEvidenceRetriever,
    make_available_batch,
    make_evidence,
)


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
        kb_id = state.get("knowledge_base_id") or "kb-default"
        evidence = make_evidence(knowledge_base_id=kb_id)
        return {
            "knowledge_base_id": kb_id,
            "retrieved_evidence": [evidence],
            "retrieved_chunks": [],
            "retrieval_status": "available",
            "retrieval_config_hash": evidence.config_hash,
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


def test_review_approve_marks_resources_approved(monkeypatch):
    result, calls = _invoke(monkeypatch, include_review=True, include_claim_check=False)

    assert calls == {"generate": 1, "review": 1}
    assert result["workflow_status"] == "completed"
    assert result["generated_resources"][0].review_status == "approved"


def test_decide_node_keeps_each_resource_review_lineage_isolated():
    text_a = LearningResource(
        resource_id="text-a", resource_spec_id="11111111-1111-1111-1111-111111111111",
        resource_type="讲义", difficulty="初级", content_text="A", knowledge_points=["a"], source_refs=[],
    )
    text_b = LearningResource(
        resource_id="text-b", resource_spec_id="22222222-2222-2222-2222-222222222222",
        resource_type="实操指南", difficulty="初级", content_text="B", knowledge_points=["b"], source_refs=[],
    )
    result = workflow_module.decide_node({
        "schema_version": "1.0", "run_id": "lineage-run", "generated_resources": [text_a, text_b],
        "review_result": {"decision": "approve", "review_ids": {"text-a": "review-a", "text-b": "review-b"}},
        "resource_review_results": {"text-a": {"decision": "approve"}, "text-b": {"decision": "approve"}},
        "resource_executions": [{"resource_id": "text-a", "representation": "text"}, {"resource_id": "text-b", "representation": "text"}],
        "revision_count": 0, "max_iterations": 1, "errors": [], "trace": [],
    })

    by_id = {resource.resource_id: resource for resource in result["generated_resources"]}
    assert by_id["text-a"].review_id == "review-a"
    assert by_id["text-b"].review_id == "review-b"
    executions = {item["resource_id"]: item for item in result["resource_executions"]}
    assert executions["text-b"]["review_id"] == "review-b"


def test_decide_node_preserves_prior_approval_for_untouched_revision_resource():
    approved = LearningResource(
        resource_id="already-approved", resource_spec_id="33333333-3333-3333-3333-333333333333",
        resource_type="实操指南", difficulty="中级", content_text="approved", knowledge_points=["a"],
        # The first review decision lives in resource_review_results. This
        # simulates a targeted second review whose in-memory resource object
        # was not refreshed, and must not hide the approved lecture.
        source_refs=[], review_status="pending_review", publication_status="unpublished",
    )
    revised = LearningResource(
        resource_id="needs-revision", resource_spec_id="44444444-4444-4444-4444-444444444444",
        resource_type="分阶测试题", difficulty="中级", content_text="revision", knowledge_points=["b"],
        source_refs=[], review_status="revision_requested", publication_status="unpublished",
    )
    result = workflow_module.decide_node({
        "schema_version": "1.0", "run_id": "targeted-revision-run",
        "generated_resources": [approved, revised],
        "review_result": {"decision": "revise", "review_ids": {"needs-revision": "review-new"}},
        "resource_review_results": {
            "already-approved": {"decision": "approve"},
            "needs-revision": {"decision": "revise"},
        },
        "resource_executions": [
            {"resource_id": "already-approved", "representation": "text"},
            {"resource_id": "needs-revision", "representation": "text"},
        ],
        "revision_count": 1, "max_iterations": 1, "errors": [], "trace": [],
    })

    by_id = {resource.resource_id: resource for resource in result["generated_resources"]}
    assert by_id["already-approved"].review_status == "approved"
    assert by_id["already-approved"].publication_status == "published"
    assert by_id["needs-revision"].review_status == "human_review"


def test_workflow_retry_guard_decides_after_max_iteration():
    assert workflow_module.decide_next({
        "review_result": {"decision": "revise"},
        "revision_count": 0,
        "max_iterations": 1,
    }) == "generate"
    assert workflow_module.decide_next({
        "review_result": {"decision": "revise"},
        "revision_count": 1,
        "max_iterations": 1,
    }) == "decide"


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

    assert result["workflow_status"] == "completed"
    assert result["generated_resources"][0].review_status == "approved"


def test_real_agent_nodes_receive_request_controls_and_share_trace_ids(monkeypatch):
    captured = {}

    def outcome(name, payload):
        def respond(call):
            captured[name] = call["messages"][-1].content
            return RawLLMResponse(content=payload)
        return respond

    gateway = LLMGateway(ScriptedLLMTransport([
        outcome("diagnosis", {
            "ability_tags": [],
            "weak_points": [],
            "recommended_difficulty": "初级",
            "suggestion": "ok",
        }),
        outcome("planner", {
            "learning_path": [{"order": 1, "topic": "node-a", "reason": "ok"}],
            "skip_points": [],
            "remedial_points": [],
            "challenge_points": [],
            "resource_requirements": {},
            "decision_reason": "ok",
        }),
        outcome("generator", {
            "difficulty": "高级",
            "title": "控制流讲义",
            "markdown_content": "# 控制流讲义\n\n## 学习目标\n\n测试资源",
            "knowledge_points": ["node-a"],
        }),
        outcome("reviewer", {
            "decision": "approve",
            "hallucination_score": 0.0,
            "issues": [],
            "difficulty_match": True,
            "coverage_rate": 1.0,
            "suggestion": "ok",
            "revision_instructions": [],
        }),
    ]))
    evidence = make_evidence(
        knowledge_base_id="kb-contract",
        query="控制流 node-a",
    )
    evidence_retriever = ScriptedEvidenceRetriever([
        make_available_batch([evidence]),
    ])

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
    result = workflow_module.build_workflow(gateway, evidence_retriever).invoke(
        build_workflow_state(_learner(), request, run_id="run-contract")
    )

    assert "diag-contract" in captured["diagnosis"]
    assert "node-a" in captured["diagnosis"]
    assert "zh-CN" in captured["planner"]
    assert "node-a" in captured["generator"]
    assert "高级" in captured["reviewer"]
    retrieval_request = evidence_retriever.calls[0]
    assert "控制流 node-a" in retrieval_request.queries
    assert retrieval_request.policy.top_k_per_query == 4
    assert retrieval_request.knowledge_base_id == "kb-contract"
    assert result["generated_resources"][0].difficulty == "高级"
    assert [item["sequence"] for item in result["trace"]] == list(
        range(1, len(result["trace"]) + 1)
    )
    assert {item["run_id"] for item in result["trace"]} == {"run-contract"}
