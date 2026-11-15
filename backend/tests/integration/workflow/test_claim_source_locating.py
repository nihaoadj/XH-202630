"""T42: neutral-v2 extraction chain through the production nodes and gateway.

A scripted transport emits the offset-free v2 output; the real extractor,
validator, locator and Judge orchestration run unchanged. No provider, no .env.
"""
import json

import pytest

from app.core.execution import execution_session
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node, claim_judge_node, claim_decide_node,
)
from tests.fakes.claim_extraction import (
    FixtureCounter,
    NeutralScriptedGateway,
    judge_all,
    neutral_settings,
    state_for_extraction,
)

RESOURCE_TYPES = ["讲义", "实操", "测试", "案例", "清单"]


def extract_every_unit_v2(call):
    """Offset-free v2 extraction: verbatim unit copy, no source_start/source_end."""
    payload = json.loads(call["messages"][-1].content)
    units = []
    for u in payload["target_units"]:
        source = u["text"]
        if not source.strip() or u["kind"] == "heading":
            units.append(dict(unit_id=u["unit_id"],
                              status="whitespace" if not source.strip() else "structure",
                              reason="synthetic", claims=[]))
        else:
            units.append(dict(unit_id=u["unit_id"], status="claims", reason="synthetic",
                              claims=[dict(claim_text=source.strip(), source_text=source,
                                           claim_type="factual", knowledge_point_id=None)]))
    return {k: payload[k] for k in ("resource_id", "resource_version", "content_hash", "batch_id")} | {"units": units}


def _extract(state, repo, gateway, counter):
    return claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                              claim_extraction_counter=counter)


def _judge(state, repo, gateway, counter):
    return claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                            claim_extraction_counter=counter)


def v2_state(text, resource_type="讲义"):
    settings = neutral_settings(claim_extraction_source_locating_mode="tolerant_v1")
    state, audit, repo, gateway, counter = state_for_extraction(text, settings=settings)
    state["generated_resources"][0] = state["generated_resources"][0].model_copy(
        update={"resource_type": resource_type})
    return state, audit, repo, gateway, counter


@pytest.mark.parametrize("resource_type", RESOURCE_TYPES)
def test_v2_chain_locates_spans_and_preserves_judge_for_each_type(resource_type):
    text = f"{resource_type}内容：这是一个包含唯一事实的连续正文片段，用于验证程序化来源定位。"
    state, _, repo, gateway, counter = v2_state(text, resource_type)
    gateway.outcomes = [extract_every_unit_v2] * 8 + [judge_all]
    with execution_session(state["run_id"], "owner"):
        state.update(_extract(state, repo, gateway, counter))
        claims = state.get("extracted_claims", [])
        assert len(claims) == 1
        c = claims[0]
        # Authoritative source write-back: the span must slice the frozen text.
        assert text[c["source_start"]:c["source_end"]] == c["source_text"]
        assert c["source_text"] == text
        extraction_calls = len(gateway.calls)
        gateway.outcomes = [judge_all]
        state.update(_judge(state, repo, gateway, counter))
        state.update(claim_decide_node(state))
    assert state["claim_check_status"] == "completed"
    # Exactly one Judge call after extraction, no source-verification call.
    assert len(gateway.calls) == extraction_calls + 1
    assert gateway.calls[-1]["context"].node_name == "claim_judge"
    for call in gateway.calls[:-1]:
        payload = json.loads(call["messages"][-1].content)
        # v2 payload/model output never carries offsets.
        assert "source_start" not in json.dumps(payload)
        assert "source_end" not in json.dumps(payload)
        assert "unit_start" not in json.dumps(payload)
        assert "unit_end" not in json.dumps(payload)
        assert "allowed_evidence" not in payload and "evidence_id" not in json.dumps(payload)
    assert all(j["evidence_ids"] == ["ev"] for j in state["claim_judgements"])


def test_v2_completion_records_bounded_location_diagnostics():
    text = "讲义内容：这是一个包含唯一事实的连续正文片段，用于验证程序化来源定位的诊断记录。"
    state, _, repo, gateway, counter = v2_state(text)
    gateway.outcomes = [extract_every_unit_v2] * 8 + [judge_all]
    with execution_session(state["run_id"], "owner"):
        state.update(_extract(state, repo, gateway, counter))
        gateway.outcomes = [judge_all]
        state.update(_judge(state, repo, gateway, counter))
        state.update(claim_decide_node(state))
    saved = repo.get(state["run_id"]).state
    result = next(iter(saved.results.values()))
    assert result.status == "completed"
    assert result.location_diagnostics is not None
    diagnostics = next(iter(result.location_diagnostics.values()))
    assert all(d.accepted for d in diagnostics)
    assert all(d.level == "exact" for d in diagnostics)
    # The diagnostic carries the frozen span; no offset came from the model.
    assert diagnostics[0].start == 0 and diagnostics[0].end == len(text)


def test_v2_policy_is_not_upgraded_to_v1_prompt():
    state, _, repo, gateway, counter = v2_state("事实正文。")
    from app.models.reviews.claim_extraction import PROMPT_VERSION_V2
    saved = repo.get(state["run_id"])
    assert saved.policy.prompt_version == PROMPT_VERSION_V2
    assert saved.policy.source_locating is not None
    assert saved.policy.source_locating.mode == "tolerant_v1"
