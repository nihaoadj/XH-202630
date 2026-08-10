from __future__ import annotations

import json

from app.agents.claim_review import claim_decide_node, claim_extract_node, claim_judge_node
from app.models.claims import ClaimMetricStatus
from app.models.schemas import LearningResource
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
