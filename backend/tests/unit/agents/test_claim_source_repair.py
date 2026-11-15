"""Bounded verbatim repair for Claim spans that miss the resource substring gate."""

from __future__ import annotations

from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claims import ClaimSourceRepairLLMOutput
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMGateway

CONTENT = "Python 使用缩进定义代码块。"


def _state() -> dict:
    resource = LearningResource(
        resource_id="res-repair",
        resource_type="讲义",
        difficulty="初级",
        content_text=CONTENT,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id="run-repair",
        version=1,
    )
    return {
        "schema_version": "1.0",
        "run_id": "run-repair",
        "generation_attempt": 1,
        "revision_count": 0,
        "max_iterations": 1,
        "workflow_deadline_at": None,
        "target_skill_nodes": ["skill-python"],
        "retrieved_evidence": [make_evidence(evidence_id="ev-repair")],
        "generated_resources": [resource],
        "review_result": {
            "decision": "approve",
            "status": "approve",
            "review_ids": {"res-repair": "review-repair"},
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


def _candidate(claim_text: str, source_text: str) -> dict:
    return {
        "claim_text": claim_text,
        "claim_type": "factual",
        "source_text": source_text,
        "source_start": 0,
        "source_end": len(source_text),
        "knowledge_point_id": "skill-python",
        "source_evidence_ids": ["ev-repair"],
    }


def test_rewritten_span_is_repaired_once_before_strict_validation():
    state = _state()
    gateway = ScriptedLLMGateway([
        {
            "resources": [{
                "resource_id": "res-repair",
                "claims": [
                    _candidate("Python 用缩进定义代码块", CONTENT),
                    # Rewritten span: the strict validator must reject this
                    # unless the bounded repair returns a verbatim copy.
                    _candidate("Python 使用缩进。", "Python 使用缩进。"),
                ],
            }],
        },
        {"claims": [{"claim_index": 1, "source_text": CONTENT}]},
    ])

    result = claim_extract_node(state, llm_gateway=gateway)

    assert result["claim_check_status"] == "pending"
    assert len(result["extracted_claims"]) == 2
    assert all(item["source_text"] in CONTENT for item in result["extracted_claims"])
    assert result["claim_failed_resource_ids"] == []
    assert len(gateway.calls) == 2
    repair_call = gateway.calls[1]
    assert repair_call["output_schema"] is ClaimSourceRepairLLMOutput
    assert repair_call["options"].max_attempts == 1
    assert repair_call["options"].allow_schema_repair is False


def test_repair_that_still_rewrites_keeps_the_resource_failed():
    state = _state()
    gateway = ScriptedLLMGateway([
        {
            "resources": [{
                "resource_id": "res-repair",
                "claims": [_candidate("Python 使用缩进。", "Python 使用缩进。")],
            }],
        },
        {"claims": [{"claim_index": 0, "source_text": "Python 使用缩进。"}]},
    ])

    result = claim_extract_node(state, llm_gateway=gateway)

    assert result["claim_check_status"] == "failed"
    assert "extracted_claims" not in result
    assert result["errors"]
    assert len(gateway.calls) == 2


def test_exact_spans_do_not_trigger_a_repair_call():
    state = _state()
    gateway = ScriptedLLMGateway([
        {
            "resources": [{
                "resource_id": "res-repair",
                "claims": [_candidate("Python 用缩进定义代码块", CONTENT)],
            }],
        },
    ])

    result = claim_extract_node(state, llm_gateway=gateway)

    assert len(result["extracted_claims"]) == 1
    assert len(gateway.calls) == 1
