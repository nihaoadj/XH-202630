"""Closed-branch equivalence on the real compiled workflow graph (H06).

The open branch is proven elsewhere (supplement sessions, rejudge, recovery).
This module proves the closed side with the actual ``build_workflow`` graph and
its real routers: with the switch off — or on with no re-judgeable gap — the
supplement nodes are never entered, and the resulting trace, claim metrics,
review decision and finalization match the legacy behaviour without the field.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.resource_workflows.learning_documents import workflow as workflow_module
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimJudgeType,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.shared.agent_contracts import build_trace_item
from app.models.shared.workflow import StepStatus
from app.services.generation import generation as generation_module
from app.services.generation.generation import build_workflow_state
from tests.fakes.evidence import make_evidence

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)
RUN_ID = "run-closed"
CONTENT = "Python 使用缩进定义代码块。RAG 召回率不应低于 95%。"

GENERAL_TYPES = ["讲义", "实操指南", "分阶测试题", "复习清单", "案例分析"]


def _learner():
    return LearnerProfile(
        learner_id="closed-user",
        learner_type="初学者",
        education="本科",
        major="计算机",
        learning_goal="验证关闭分支",
        knowledge_base_id="kb-closed",
    )


def _trace(state, name):
    return build_trace_item(
        state, agent_name=name, action=name, status=StepStatus.SUCCESS,
        input_summary="safe", output_summary="safe", decision_reason="test",
    )


def _claim(index: int, text: str, start: int, claim_type: ClaimType = ClaimType.FACTUAL) -> ClaimRecord:
    return ClaimRecord(
        claim_id="clm_" + f"{index:032x}",
        run_id=RUN_ID, resource_id="res-closed", resource_version=1,
        review_id="review-closed", claim_index=index,
        claim_text=text, claim_type=claim_type,
        source_text=text, source_start=start, source_end=start + len(text),
        source_text_hash="a" * 64, extractor_prompt_version="p0-06-extract-v3",
        claim_hash="b" * 64, created_at=NOW,
    )


def _judgement(claim: ClaimRecord, verdict: ClaimVerdict) -> ClaimJudgement:
    return ClaimJudgement(
        judgement_id="jdg_" + claim.claim_id[4:],
        claim_id=claim.claim_id, run_id=claim.run_id, resource_id=claim.resource_id,
        resource_version=1, review_id=claim.review_id,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-closed"] if verdict is ClaimVerdict.SUPPORTED else [],
        reason="round0", judge_type=ClaimJudgeType.LLM,
        judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
    )


def _claim_payloads(claims, verdicts):
    return (
        [claim.model_dump(mode="json") for claim in claims],
        [_judgement(claim, verdict).model_dump(mode="json")
         for claim, verdict in zip(claims, verdicts)],
    )


def _invoke(
    monkeypatch,
    *,
    resource_types,
    include_claim_check,
    send_retrieval_flag,  # True / False / "omit"
    claims=(), verdicts=(),
    claim_check_status="completed",
    supplement_policy=False,
):
    calls = {
        "plan": 0, "generate": 0, "review": 0,
        "claim_extract": 0, "claim_judge": 0,
        "claim_evidence_retrieve": 0, "claim_evidence_rejudge": 0,
    }

    def diagnose(state):
        return {"diagnosis": {}, "trace": [_trace(state, "diagnosis")], "errors": []}

    def retrieve(state):
        return {
            "knowledge_base_id": "kb-closed",
            "retrieval_status": "available",
            "retrieved_evidence": [make_evidence(knowledge_base_id="kb-closed")],
            "retrieval_config_hash": "2" * 64,
            "retrieval_query_hashes": ["1" * 64],
            "retrieval_candidate_count": 1,
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
        resources = [
            LearningResource(
                resource_id=f"res-closed-{index}",
                resource_type=resource_type,
                difficulty="初级",
                content_text=CONTENT,
                knowledge_points=["skill-python"],
                source_refs=[],
                run_id=state["run_id"],
            )
            for index, resource_type in enumerate(state["resource_types"], start=1)
        ]
        return {"generated_resources": resources, "trace": [_trace(state, "generator")], "errors": []}

    def review(state):
        calls["review"] += 1
        review_ids = {
            resource.resource_id: f"review-{resource.resource_id}"
            for resource in state.get("generated_resources", [])
        }
        return {
            "review_result": {
                "decision": "approve", "status": "approve", "passed": True,
                "hallucination_score": 0.0, "review_ids": review_ids,
                "issues": [], "revision_instructions": [],
            },
            "resource_review_results": {
                resource_id: {"decision": "approve", "status": "approve"}
                for resource_id in review_ids
            },
            "trace": [_trace(state, "reviewer")],
            "errors": [],
        }

    def claim_extract(state):
        calls["claim_extract"] += 1
        resource = state["generated_resources"][0]
        payload_claims = [
            dict(claim, resource_id=resource.resource_id,
                 review_id=f"review-{resource.resource_id}")
            for claim in claims
        ]
        return {
            "extracted_claims": payload_claims,
            "claim_check_status": "pending",
            "trace": [_trace(state, "claim_extractor")],
            "errors": [],
        }

    def claim_judge(state):
        calls["claim_judge"] += 1
        return {
            "claim_judgements": list(verdicts),
            "claim_check_status": claim_check_status,
            "claim_failed_resource_ids": [],
            "claim_metrics": {},
            "trace": [_trace(state, "claim_judge")],
            "errors": [],
        }

    def claim_evidence_retrieve(state, **kwargs):
        calls["claim_evidence_retrieve"] += 1
        return {"claim_evidence_retrieval_refs": [], "trace": [_trace(state, "supplement")], "errors": []}

    def claim_evidence_rejudge(state, **kwargs):
        calls["claim_evidence_rejudge"] += 1
        return {"trace": [_trace(state, "rejudge")], "errors": []}

    monkeypatch.setattr(workflow_module, "diagnose_node", diagnose)
    monkeypatch.setattr(workflow_module, "retrieve_node", retrieve)
    monkeypatch.setattr(workflow_module, "plan_node", plan)
    monkeypatch.setattr(workflow_module, "generate_node", generate)
    monkeypatch.setattr(workflow_module, "review_node", review)
    monkeypatch.setattr(workflow_module, "claim_extract_node", claim_extract)
    monkeypatch.setattr(workflow_module, "claim_judge_node", claim_judge)
    monkeypatch.setattr(workflow_module, "claim_evidence_retrieve_node", claim_evidence_retrieve)
    monkeypatch.setattr(workflow_module, "claim_evidence_rejudge_node", claim_evidence_rejudge)

    # Claim audit without a submission preflight is only valid for the legacy
    # extraction strategy; freeze that strategy so the graph accepts the state.
    from app.config import Settings

    monkeypatch.setattr(
        generation_module, "get_settings",
        lambda: Settings(_env_file=None, claim_extraction_strategy="legacy_v3"),
    )

    fields = {
        "learner_id": _learner().learner_id,
        "topic": "关闭分支等价",
        "knowledge_base_id": "kb-closed",
        "target_skill_nodes": ["skill-python"],
        "resource_types": resource_types,
        "include_review": True,
        "include_claim_check": include_claim_check,
    }
    if send_retrieval_flag != "omit":
        fields["include_claim_evidence_retrieval"] = send_retrieval_flag
    request = GenerateRequest.model_validate(fields)

    supplement_snapshot = None
    if supplement_policy:
        from app.models.reviews.claim_evidence_retrieval import (
            ClaimEvidenceRetrievalPolicyV1,
        )

        policy = ClaimEvidenceRetrievalPolicyV1(
            query_prompt_hash="a" * 64, query_schema_hash="b" * 64,
            rejudge_prompt_hash="c" * 64, rejudge_schema_hash="d" * 64,
        )
        supplement_snapshot = {
            "claim_evidence_retrieval_policy": policy.model_dump(mode="json"),
            "claim_evidence_retrieval_policy_hash": policy.policy_hash,
        }
    state = build_workflow_state(
        _learner(), request, run_id=RUN_ID,
        claim_evidence_retrieval_snapshot=supplement_snapshot,
    )

    result = workflow_module.build_workflow().invoke(state)
    return result, calls


def _projection(result):
    """Comparable closed-branch projection: trace, metrics, publication."""

    return {
        "nodes": [item.get("agent_name") for item in result.get("trace", [])],
        "claim_check_status": result.get("claim_check_status"),
        "claim_metrics": result.get("claim_metrics", {}),
        "review_decision": (result.get("review_result") or {}).get("decision"),
        "workflow_status": result.get("workflow_status"),
        "final_decision": result.get("final_decision"),
        "error_codes": sorted({item.get("code") for item in result.get("errors", []) if item.get("code")}),
        "supplement_refs": result.get("claim_evidence_retrieval_refs", []),
        "hard_blocks": result.get("claim_evidence_hard_block_resource_ids", []),
    }


def test_five_resource_types_closed_branch_adds_zero_calls_and_matches_legacy(monkeypatch):
    result, calls = _invoke(
        monkeypatch, resource_types=GENERAL_TYPES,
        include_claim_check=False, send_retrieval_flag=False,
    )
    legacy, legacy_calls = _invoke(
        monkeypatch, resource_types=GENERAL_TYPES,
        include_claim_check=False, send_retrieval_flag="omit",
    )

    assert calls["claim_extract"] == 0 and calls["claim_judge"] == 0
    assert calls["claim_evidence_retrieve"] == 0 and calls["claim_evidence_rejudge"] == 0
    assert legacy_calls["claim_evidence_retrieve"] == 0
    assert _projection(result) == _projection(legacy)
    assert result["workflow_status"] == "completed"
    assert len(result["generated_resources"]) == 5


def test_all_supported_first_round_never_enters_the_supplement_nodes(monkeypatch):
    claims, verdicts = _claim_payloads(
        [_claim(1, "Python 使用缩进定义代码块", 0), _claim(2, "RAG 召回率不应低于 95%", CONTENT.index("RAG"))],
        [ClaimVerdict.SUPPORTED, ClaimVerdict.SUPPORTED],
    )
    result, calls = _invoke(
        monkeypatch, resource_types=["讲义"], include_claim_check=True,
        send_retrieval_flag=True, claims=claims, verdicts=verdicts,
        supplement_policy=True,
    )

    assert calls["claim_evidence_retrieve"] == 0
    assert calls["claim_evidence_rejudge"] == 0
    assert result["claim_check_status"] == "completed"
    assert _projection(result)["supplement_refs"] == []


def test_incomplete_first_judge_skips_supplements(monkeypatch):
    claims, verdicts = _claim_payloads(
        [_claim(1, "Python 使用缩进定义代码块", 0)],
        [ClaimVerdict.NOT_IN_EVIDENCE],
    )
    result, calls = _invoke(
        monkeypatch, resource_types=["讲义"], include_claim_check=True,
        send_retrieval_flag=True, claims=claims, verdicts=verdicts,
        claim_check_status="failed", supplement_policy=True,
    )

    assert calls["claim_evidence_retrieve"] == 0
    assert result["claim_check_status"] == "failed"


def test_non_factual_claims_alone_never_request_supplements(monkeypatch):
    claim = _claim(1, "请完成本节练习。", 0, claim_type=ClaimType.NON_FACTUAL)
    claims, verdicts = _claim_payloads([claim], [ClaimVerdict.NON_FACTUAL])
    result, calls = _invoke(
        monkeypatch, resource_types=["讲义"], include_claim_check=True,
        send_retrieval_flag=True, claims=claims, verdicts=verdicts,
        supplement_policy=True,
    )

    assert calls["claim_evidence_retrieve"] == 0
    assert calls["claim_evidence_rejudge"] == 0


def test_closed_switch_with_missing_evidence_matches_the_legacy_trace(monkeypatch):
    """A not-in-evidence gap stays untouched when the switch is closed."""

    claims, verdicts = _claim_payloads(
        [_claim(1, "Python 使用缩进定义代码块", 0), _claim(2, "RAG 召回率不应低于 95%", CONTENT.index("RAG"))],
        [ClaimVerdict.SUPPORTED, ClaimVerdict.NOT_IN_EVIDENCE],
    )
    closed, closed_calls = _invoke(
        monkeypatch, resource_types=["讲义"], include_claim_check=True,
        send_retrieval_flag=False, claims=claims, verdicts=verdicts,
        supplement_policy=False,
    )
    legacy, legacy_calls = _invoke(
        monkeypatch, resource_types=["讲义"], include_claim_check=True,
        send_retrieval_flag="omit", claims=claims, verdicts=verdicts,
        supplement_policy=False,
    )

    assert closed_calls["claim_evidence_retrieve"] == 0
    assert legacy_calls["claim_evidence_retrieve"] == 0
    assert _projection(closed) == _projection(legacy)
    verdict_map = {
        item["claim_id"]: item["verdict"] for item in closed["claim_judgements"]
    }
    # The gap was never rejudged: the original not-in-evidence verdict survives.
    assert sorted(verdict_map.values()) == ["not_in_evidence", "supported"]
    nodes = _projection(closed)["nodes"]
    assert nodes[:7] == [
        "diagnosis", "retriever", "evidence_gate", "planner", "generator",
        "reviewer", "claim_extractor",
    ]
    assert "supplement" not in nodes
