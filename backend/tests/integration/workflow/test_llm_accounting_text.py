"""Text full-chain accounting integration tests (T41 P3).

Runs the production claim/review/generation entry points with the real
``LLMGateway`` (scripted transport) inside the GenerationService-level task
segment: every logical call must be observed with its stage attribution and
the business projections must be identical to a no-scope run.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node,
    claim_judge_node,
)
from app.core.llm import accounting
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.llm import (
    LLMCallOptions,
    RawLLMResponse,
    StructuredOutputMode,
)
from tests.fakes.evidence import make_evidence
from tests.fakes.llm import ScriptedLLMTransport
from app.core.llm.gateway import LLMGateway
from app.agents.shared.llm_accounting import text_run_segment


@pytest.fixture()
def collected(monkeypatch):
    monkeypatch.setattr(accounting, "_enabled", True)
    submissions = []

    class _Publisher:
        def submit(self, submission):
            submissions.append(submission)
            return True

    monkeypatch.setattr(accounting, "_publisher", _Publisher())
    yield submissions
    accounting.uninstall_publisher()


def _real_gateway(outcomes):
    transport = ScriptedLLMTransport(
        [RawLLMResponse(content=json.dumps(outcome, ensure_ascii=False)) for outcome in outcomes]
    )
    return LLMGateway(
        transport,
        default_options=LLMCallOptions(
            max_attempts=1,
            request_timeout_seconds=5.0,
            structured_output_mode=StructuredOutputMode.FUNCTION_CALLING,
        ),
        sleep=lambda _s: None,
    )


def _state(run_id="run-text"):
    content = "Python 使用缩进定义代码块。"
    resource = LearningResource(
        resource_id="res-claim",
        resource_type="讲义",
        difficulty="初级",
        content_text=content,
        knowledge_points=["skill-python"],
        source_refs=[],
        run_id=run_id,
        version=1,
    )
    return {
        "schema_version": "1.0",
        "run_id": run_id,
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


_EXTRACT_OUTCOME = {
    "resources": [
        {
            "resource_id": "res-claim",
            "claims": [
                {
                    "claim_text": "Python 使用缩进定义代码块",
                    "claim_type": "factual",
                    "source_text": "Python 使用缩进定义代码块。",
                    "source_start": 0,
                    "source_end": 14,
                    "knowledge_point_id": "skill-python",
                    "source_evidence_ids": ["ev-claim"],
                }
            ],
        }
    ],
}


def test_claim_extract_and_judge_observed_with_stages(collected):
    gateway = _real_gateway(
        [
            _EXTRACT_OUTCOME,
            {
                "judgements": [
                    {
                        "claim_id": "PLACEHOLDER",
                        "verdict": "supported",
                        "evidence_ids": ["ev-claim"],
                        "reason": "冻结证据支持该陈述",
                        "confidence": 0.95,
                    }
                ],
            },
        ]
    )
    state = _state()
    with text_run_segment("run-text"):
        extracted = claim_extract_node(state, llm_gateway=gateway)
        state.update(extracted)
        claim_id = state["extracted_claims"][0]["claim_id"]
        # Patch the scripted judge outcome to reference the materialized id.
        transport = gateway.transport
        transport.outcomes[0] = RawLLMResponse(
            content=json.dumps(
                {
                    "judgements": [
                        {
                            "claim_id": claim_id,
                            "verdict": "supported",
                            "evidence_ids": ["ev-claim"],
                            "reason": "冻结证据支持该陈述",
                            "confidence": 0.95,
                        }
                    ]
                },
                ensure_ascii=False,
            )
        )
        judged = claim_judge_node(state, llm_gateway=gateway)
    state.update(judged)
    assert state["claim_check_status"] == "completed"
    assert [item["verdict"] for item in state["claim_judgements"]] == ["supported"]
    segments = [submission.segment for submission in collected]
    assert len(segments) == 1
    calls = segments[0].calls
    stages = [call.stage for call in calls]
    assert stages.count("claim_extract") == 1
    assert stages.count("claim_judge") == 1
    extract_call = next(call for call in calls if call.stage == "claim_extract")
    assert extract_call.attribution in {"resource", "task"}
    # The scripted transport reports no usage: it must stay unknown instead of
    # being materialized as a complete zero-token call.
    assert extract_call.usage_input_tokens is None
    assert extract_call.usage_complete is False
    assert extract_call.known_input_tokens == 0
    judge_call = next(call for call in calls if call.stage == "claim_judge")
    assert judge_call.outcome == "success"


def test_business_projection_identical_with_and_without_scope(collected):
    stable_claim_fields = (
        "schema_version", "run_id", "resource_id", "resource_version", "review_id",
        "claim_index", "claim_text", "claim_type", "source_text", "source_start",
        "source_end", "source_text_hash", "knowledge_point_id", "source_evidence_ids",
        "extraction_method", "extractor_model", "claim_hash",
    )
    stable_trace_fields = (
        "agent_name", "action", "status", "input_summary", "output_summary",
        "decision_reason", "resource_ids", "review_ids", "evidence_refs",
        "error_code", "error_message",
    )

    def _run():
        state = _state()
        gateway = _real_gateway([_EXTRACT_OUTCOME, {"judgements": []}])
        extracted = claim_extract_node(state, llm_gateway=gateway)
        state.update(extracted)
        # Runtime-only identity/timing fields are excluded: they differ between
        # any two executions even without accounting installed.
        return {
            "claims": [
                {key: claim.get(key) for key in stable_claim_fields}
                for claim in state["extracted_claims"]
            ],
            "trace": [
                {key: item.get(key) for key in stable_trace_fields}
                for item in state["trace"]
            ],
        }

    without_scope = _run()
    with text_run_segment("run-text-projection"):
        with_scope = _run()
    assert without_scope["claims"] == with_scope["claims"]
    assert without_scope["trace"] == with_scope["trace"]
    assert collected, "the scoped run must have produced observations"


def test_cross_run_isolation_no_leakage(collected):
    first_state = _state(run_id="run-a")
    second_state = _state(run_id="run-b")
    with text_run_segment("run-a"):
        claim_extract_node(first_state, llm_gateway=_real_gateway([_EXTRACT_OUTCOME]))
    with text_run_segment("run-b"):
        claim_extract_node(second_state, llm_gateway=_real_gateway([_EXTRACT_OUTCOME]))
    by_run = {}
    for submission in collected:
        by_run.setdefault(submission.segment.run_id, []).extend(submission.segment.calls)
    assert set(by_run) == {"run-a", "run-b"}
    assert all(call.run_id == run for run, calls in by_run.items() for call in calls)


def test_recorded_step_scope_binds_stage(monkeypatch, collected):
    from app.agents.shared.llm_accounting import recorded_step_scope
    from app.models.shared.agent_contracts import (
        bind_recorded_step_context,
        reset_recorded_step_context,
    )

    gateway = _real_gateway([_EXTRACT_OUTCOME])
    state = _state()
    step_context = {
        "step_id": "step-acc",
        "sequence": 7,
        "attempt": 1,
        "started_at": datetime.now(timezone.utc),
        "node_name": "claim_extract",
        "agent_name": "claim_extractor",
    }
    # RecordedNode binds the business step identity first, then the accounting
    # stage scope observes it; reproduce that exact order here.
    token = bind_recorded_step_context(step_context)
    try:
        with text_run_segment("run-text"):
            with recorded_step_scope(step_context):
                claim_extract_node(state, llm_gateway=gateway)
    finally:
        reset_recorded_step_context(token)
    call = collected[0].segment.calls[0]
    assert call.step_id == "step-acc"
    assert call.stage_sequence == 7
    assert call.node_name == "claim_extractor"


def test_resource_generation_agent_binds_resource_scope(collected):
    from tests.unit.agents.test_resource_type_agents import _inputs

    spec, context, _evidence = _inputs("复习清单")
    from tests.unit.agents.test_resource_type_agents import CHECKLIST_PAYLOAD

    gateway = _real_gateway([CHECKLIST_PAYLOAD])
    from app.agents.resource_agents.checklist import ReviewChecklistAgent

    agent = ReviewChecklistAgent()
    with text_run_segment(context.run_id):
        artifact = agent.generate(spec, context, llm_gateway=gateway)
    assert artifact.metadata.resource_type == "复习清单"
    call = collected[0].segment.calls[0]
    assert call.attribution == "resource"
    assert spec.resource_spec_id in call.resource_labels
    assert "复习清单" in call.resource_labels
