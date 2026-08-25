from __future__ import annotations

import json

from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_decide_node, claim_extract_node, claim_judge_node
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.core.security.errors import ErrorCode
from app.core.llm.gateway import LLMGatewayError
from app.models.shared.agent_contracts import make_error_info
from app.models.reviews.claims import ClaimMetricStatus
from app.models.learning_documents.schemas import LearningResource
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway


def _state():
    content = "Python 使用缩进定义代码块。"
    resource = LearningResource(
        resource_id="res-claim",
        resource_type="讲义",
        difficulty="初级",
        content_text=content,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id="run-claim",
        version=1,
    )
    return {
        "schema_version": "1.0",
        "run_id": "run-claim",
        "generation_attempt": 1,
        "revision_count": 0,
        "max_iterations": 1,
        "workflow_deadline_at": None,
        "target_skill_nodes": ["skill-python"],
        "retrieved_evidence": [make_evidence(evidence_id="ev-claim")],
        "generated_resources": [resource],
        "review_result": {
            "decision": "approve",
            "status": "approve",
            "review_ids": {"res-claim": "review-claim"},
            "issues": [],
            "revision_instructions": [],
            "hallucination_score": 0.1,
        },
        "include_review": True,
        "include_claim_check": True,
        "claim_check_status": "pending",
        "trace": [],
        "errors": [],
    }


def test_supported_claim_completes_and_approves():
    state = _state()
    content = state["generated_resources"][0].content_text
    extractor = ScriptedLLMGateway([{
        "resources": [{
            "resource_id": "res-claim",
            "claims": [{
                "claim_text": "Python 使用缩进定义代码块",
                "claim_type": "factual",
                "source_text": content,
                "source_start": 0,
                "source_end": len(content),
                "knowledge_point_id": "skill-python",
                "source_evidence_ids": ["ev-claim"],
            }],
        }],
    }])
    extracted = claim_extract_node(state, llm_gateway=extractor)
    state.update(extracted)
    claim_id = state["extracted_claims"][0]["claim_id"]
    judge = ScriptedLLMGateway([{
        "judgements": [{
            "claim_id": claim_id,
            "verdict": "supported",
            "evidence_ids": ["ev-claim"],
            "reason": "冻结证据支持该陈述",
            "confidence": 0.95,
        }],
    }])
    state.update(claim_judge_node(state, llm_gateway=judge))
    state.update(claim_decide_node(state))

    assert state["claim_check_status"] == "completed"
    assert state["review_result"]["decision"] == "approve"
    assert state["review_result"]["claim_hallucination_rate"] == 0.0
    assert state["claim_metrics"]["res-claim"]["metric_status"] == ClaimMetricStatus.COMPLETE.value


def test_structured_assessment_uses_internal_audit_instead_of_public_markdown_claims():
    state = _state()
    assessment = LearningResource(
        resource_id="res-assessment", resource_type="分阶测试题", difficulty="初级",
        content_text="# 测评\n\n### 单选题（基础）\n\n题干不含答案。",
        knowledge_points=["skill-python"], source_refs=[], run_id="run-claim", version=1,
        assessment_payload={
            "schema_version": "2.0", "title": "内部题卷", "instructions": "内部审核使用",
            "node_blocks": [{"skill_node_id": "skill-python", "skill_node_name": "Python",
                "single_choice_questions": [{"answer_option_ids": ["A"], "evidence_ids": ["ev-claim"]}],
                "multiple_choice_questions": [], "short_answer_questions": []}],
        },
    )
    state["generated_resources"] = [assessment]
    state["review_result"]["review_ids"] = {assessment.resource_id: "review-assessment"}

    extracted = claim_extract_node(state, llm_gateway=ScriptedLLMGateway([]))
    state.update(extracted)
    assert state["extracted_claims"] == []
    assert state["assessment_claim_skipped_resource_ids"] == [assessment.resource_id]

    state.update(claim_judge_node(state, llm_gateway=ScriptedLLMGateway([])))
    state.update(claim_decide_node(state))
    assert state["claim_check_status"] == "completed"
    assert state["review_result"]["decision"] == "approve"
    assert state["claim_metrics"][assessment.resource_id]["metric_status"] == ClaimMetricStatus.NOT_APPLICABLE.value
    assert state["claim_metrics"][assessment.resource_id]["audit_mode"] == "structured_assessment_internal"


def test_not_in_evidence_generates_claim_targeted_revision():
    state = _state()
    content = state["generated_resources"][0].content_text
    extracted = claim_extract_node(state, llm_gateway=ScriptedLLMGateway([{
        "resources": [{"resource_id": "res-claim", "claims": [{
            "claim_text": "Python 使用缩进定义代码块",
            "claim_type": "factual",
            "source_text": content,
            "source_start": 0,
            "source_end": len(content),
            "knowledge_point_id": "skill-python",
            "source_evidence_ids": [],
        }]}],
    }]))
    state.update(extracted)
    claim_id = state["extracted_claims"][0]["claim_id"]
    state.update(claim_judge_node(state, llm_gateway=ScriptedLLMGateway([{
        "judgements": [{
            "claim_id": claim_id,
            "verdict": "not_in_evidence",
            "evidence_ids": [],
            "reason": "冻结证据没有覆盖该事实",
            "confidence": 0.8,
        }],
    }])))
    state.update(claim_decide_node(state))

    assert state["review_result"]["decision"] == "revise"
    assert state["review_result"]["claim_hallucination_rate"] == 1.0
    assert state["review_result"]["revision_instructions"][-1]["target_claim_ids"] == [claim_id]


def test_forged_evidence_fails_closed_without_leaking_claim_text():
    state = _state()
    content = state["generated_resources"][0].content_text
    result = claim_extract_node(state, llm_gateway=ScriptedLLMGateway([{
        "resources": [{"resource_id": "res-claim", "claims": [{
            "claim_text": "Python 使用缩进定义代码块",
            "claim_type": "factual",
            "source_text": content,
            "source_start": 0,
            "source_end": len(content),
            "knowledge_point_id": "skill-python",
            "source_evidence_ids": ["forged-evidence"],
        }]}],
    }]))

    assert result["claim_check_status"] == "failed"
    assert result["review_result"]["decision"] == "human_review"
    assert "Python" not in json.dumps(result["trace"], ensure_ascii=False)


def test_claim_extractor_and_judge_invoke_once_per_resource():
    state = _state()
    second_content = "检索结果必须绑定冻结证据。"
    second = LearningResource(
        resource_id="res-claim-second",
        resource_type="实操指南",
        difficulty="初级",
        content_text=second_content,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id="run-claim",
        version=1,
    )
    state["generated_resources"].append(second)
    state["review_result"]["review_ids"][second.resource_id] = "review-claim-second"
    first_content = state["generated_resources"][0].content_text
    extractor = ScriptedLLMGateway([
        {"resources": [{"resource_id": "res-claim", "claims": [{
            "claim_text": "Python 使用缩进定义代码块",
            "claim_type": "factual",
            "source_text": first_content,
            "source_start": 0,
            "source_end": len(first_content),
            "knowledge_point_id": "skill-python",
            "source_evidence_ids": ["ev-claim"],
        }]}]},
        {"resources": [{"resource_id": "res-claim-second", "claims": [{
            "claim_text": "检索结果必须绑定冻结证据",
            "claim_type": "factual",
            "source_text": second_content,
            "source_start": 0,
            "source_end": len(second_content),
            "knowledge_point_id": "skill-python",
            "source_evidence_ids": ["ev-claim"],
        }]}]},
    ])
    state.update(claim_extract_node(state, llm_gateway=extractor))

    assert len(extractor.calls) == 2
    extractor_payloads = [
        json.loads(call["messages"][-1].content)
        for call in extractor.calls
    ]
    assert [len(item["resources"]) for item in extractor_payloads] == [1, 1]
    assert [item["resources"][0]["resource_id"] for item in extractor_payloads] == [
        "res-claim",
        "res-claim-second",
    ]

    claim_ids = {
        item["resource_id"]: item["claim_id"]
        for item in state["extracted_claims"]
    }
    judge = ScriptedLLMGateway([
        {"judgements": [{
            "claim_id": claim_ids["res-claim"],
            "verdict": "supported",
            "evidence_ids": ["ev-claim"],
            "reason": "证据支持",
            "confidence": 0.9,
        }]},
        {"judgements": [{
            "claim_id": claim_ids["res-claim-second"],
            "verdict": "supported",
            "evidence_ids": ["ev-claim"],
            "reason": "证据支持",
            "confidence": 0.9,
        }]},
    ])
    state.update(claim_judge_node(state, llm_gateway=judge))

    assert len(judge.calls) == 2
    judge_payloads = [json.loads(call["messages"][-1].content) for call in judge.calls]
    assert [len({claim["resource_id"] for claim in item["claims"]}) for item in judge_payloads] == [1, 1]
    assert set(state["claim_metrics"]) == {"res-claim", "res-claim-second"}


def test_claim_failure_is_isolated_to_one_resource_and_other_resource_publishes():
    state = _state()
    second_content = "检索结果必须绑定冻结证据。"
    second = LearningResource(
        resource_id="res-claim-second",
        resource_type="实操指南",
        difficulty="初级",
        content_text=second_content,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id="run-claim",
        version=1,
    )
    state["generated_resources"].append(second)
    state["review_result"]["review_ids"][second.resource_id] = "review-claim-second"
    state["resource_review_results"] = {
        "res-claim": {"decision": "approve"},
        "res-claim-second": {"decision": "approve"},
    }
    first_content = state["generated_resources"][0].content_text
    gateway_error = LLMGatewayError(
        error=make_error_info(
            ErrorCode.LLM_UPSTREAM_UNAVAILABLE,
            source="claim_extractor",
            category="upstream",
        ),
        call_id="claim-extract-second-failed",
        retry_count=1,
        latency_ms=10,
        attempts=[],
    )
    extracted = claim_extract_node(state, llm_gateway=ScriptedLLMGateway([
        {"resources": [{"resource_id": "res-claim", "claims": [{
            "claim_text": "Python 使用缩进定义代码块",
            "claim_type": "factual",
            "source_text": first_content,
            "source_start": 0,
            "source_end": len(first_content),
            "knowledge_point_id": "skill-python",
            "source_evidence_ids": ["ev-claim"],
        }]}]},
        gateway_error,
    ]))
    state.update(extracted)
    assert state["claim_failed_resource_ids"] == ["res-claim-second"]
    claim_id = state["extracted_claims"][0]["claim_id"]
    state.update(claim_judge_node(state, llm_gateway=ScriptedLLMGateway([{
        "judgements": [{
            "claim_id": claim_id,
            "verdict": "supported",
            "evidence_ids": ["ev-claim"],
            "reason": "冻结证据支持",
            "confidence": 0.9,
        }],
    }])))
    state.update(claim_decide_node(state))
    finalized = decide_node(state)

    by_id = {item.resource_id: item for item in finalized["generated_resources"]}
    assert state["review_result"]["decision"] == "human_review"
    assert by_id["res-claim"].publication_status == "published"
    assert by_id["res-claim"].review_status == "approved"
    assert by_id["res-claim-second"].publication_status == "unpublished"
    assert by_id["res-claim-second"].review_status == "human_review"
