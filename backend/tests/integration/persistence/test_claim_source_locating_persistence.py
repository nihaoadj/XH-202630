"""T42: v2 output/diagnostic persistence, CAS and legacy byte-compat (Memory + SQLite)."""
import json

import pytest

from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
from app.core.execution import execution_session
from app.models.reviews.claim_extraction import (
    BatchOutput,
    BatchOutputV2,
    NeutralCandidate,
    NeutralCandidateV2,
    UnitOutput,
    UnitOutputV2,
    output_matches_policy,
)
from app.agents.resource_workflows.learning_documents.claim_review_agent import claim_extract_node
from tests.fakes.claim_extraction import (
    FixtureCounter,
    NeutralScriptedGateway,
    judge_all,
    neutral_settings,
    state_for_extraction,
)
from tests.fakes.persistence import sqlite_repository


def v2_policy():
    return freeze_policy(neutral_settings(claim_extraction_source_locating_mode="tolerant_v1"),
                         NeutralScriptedGateway([]), FixtureCounter())


def v1_policy():
    return freeze_policy(neutral_settings(), NeutralScriptedGateway([]), FixtureCounter())


def extract_every_unit_v2(call):
    payload = json.loads(call["messages"][-1].content)
    units = []
    for u in payload["target_units"]:
        source = u["text"]
        if not source.strip() or u["kind"] == "heading":
            units.append(dict(unit_id=u["unit_id"], status="whitespace" if not source.strip() else "structure",
                              reason="synthetic", claims=[]))
        else:
            units.append(dict(unit_id=u["unit_id"], status="claims", reason="synthetic",
                              claims=[dict(claim_text=source.strip(), source_text=source,
                                           claim_type="factual", knowledge_point_id=None)]))
    return {k: payload[k] for k in ("resource_id", "resource_version", "content_hash", "batch_id")} | {"units": units}


def _v1_output(content_hash, batch_id="b"):
    return BatchOutput(resource_id="r", resource_version=1, content_hash=content_hash, batch_id=batch_id,
                       units=[UnitOutput(unit_id="u", status="claims", reason="synthetic",
                                         claims=[NeutralCandidate(claim_text="事实", claim_type="factual",
                                                                  source_text="事实", source_start=0, source_end=2)])])


def _v2_output(content_hash, batch_id="b"):
    return BatchOutputV2(resource_id="r", resource_version=1, content_hash=content_hash, batch_id=batch_id,
                         units=[UnitOutputV2(unit_id="u", status="claims", reason="synthetic",
                                             claims=[NeutralCandidateV2(claim_text="事实", claim_type="factual",
                                                                        source_text="事实")])])


def test_output_matches_policy_distinguishes_v1_and_v2():
    h = "a" * 64
    assert output_matches_policy(v1_policy(), _v1_output(h)) is True
    assert output_matches_policy(v1_policy(), _v2_output(h)) is False
    assert output_matches_policy(v2_policy(), _v2_output(h)) is True
    assert output_matches_policy(v2_policy(), _v1_output(h)) is False


@pytest.mark.parametrize("storage_kind", ["memory", "sqlite"])
def test_v2_completed_result_roundtrips_with_diagnostics(tmp_path, storage_kind):
    from app.core.execution import ExecutionFence, execution_fence
    settings = neutral_settings(claim_extraction_source_locating_mode="tolerant_v1")
    gateway = NeutralScriptedGateway([extract_every_unit_v2, judge_all])
    text = "这是一段包含唯一事实的正文，用于验证 v2 结果的持久化与诊断记录。"
    if storage_kind == "memory":
        state, _, repo, gateway, counter = state_for_extraction(text, settings=settings, gateway=gateway)
        engine = None
    else:
        audit, engine = sqlite_repository(tmp_path)
        with execution_fence(ExecutionFence("run-neutral", "owner")):
            state, _, repo, gateway, counter = state_for_extraction(text, settings=settings, gateway=gateway, audit=audit)
    fence = execution_fence(ExecutionFence(state["run_id"], "owner"))
    with fence, execution_session(state["run_id"], "owner"):
        state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                        claim_extraction_counter=counter))
    saved = repo.get(state["run_id"])
    assert saved.policy.prompt_version == "claim-extract-neutral-v2"
    assert saved.policy.source_locating is not None
    result = next(iter(saved.state.results.values()))
    assert result.status == "completed"
    output = next(iter(result.outputs.values()))
    assert isinstance(output, BatchOutputV2)
    assert output_matches_policy(saved.policy, output)
    assert result.location_diagnostics is not None
    diagnostics = next(iter(result.location_diagnostics.values()))
    assert all(d.accepted for d in diagnostics)
    claim = result.final_claims[0]
    assert text[claim.source_start:claim.source_end] == claim.source_text
    if engine is not None:
        engine.dispose()


def test_legacy_v1_policy_keeps_byte_identical_serialization_without_source_locating():
    p = v1_policy()
    raw = p.model_dump(mode="json")
    assert "source_locating" not in raw
    assert "density_batching" in raw  # unrelated T37 sub-contract still present
    again = type(p).model_validate(raw).model_dump(mode="json")
    assert again == raw
