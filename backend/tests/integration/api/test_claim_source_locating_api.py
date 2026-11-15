"""T42: public Claim DTO stays unchanged and never leaks private locating audit."""
import json

from app.core.execution import execution_session
from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    claim_extract_node, claim_judge_node, claim_decide_node,
)
from app.models.reviews.claims import ClaimRecord, RunClaimsResponse
from app.models.reviews.claim_extraction import SourceLocatingPolicy
from tests.fakes.claim_extraction import (
    FixtureCounter,
    NeutralScriptedGateway,
    judge_all,
    neutral_settings,
    state_for_extraction,
)


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


def test_claim_record_public_contract_has_no_private_locating_fields():
    # The public DTO never carries the private locating policy or diagnostics.
    assert "source_locating" not in ClaimRecord.model_json_schema().get("properties", {})
    assert "location_diagnostics" not in ClaimRecord.model_json_schema().get("properties", {})
    assert "source_locating" not in RunClaimsResponse.model_json_schema().get("properties", {})
    assert "location_diagnostics" not in RunClaimsResponse.model_json_schema().get("properties", {})
    # Source span fields remain part of the public contract.
    for name in ("source_start", "source_end", "source_text"):
        assert name in ClaimRecord.model_json_schema()["properties"]


def test_v2_claim_exposes_accurate_span_and_no_private_audit():
    text = "讲义内容：这是一段包含唯一事实的正文，用于验证公开 Claim 契约不泄漏私有定位审计。"
    settings = neutral_settings(claim_extraction_source_locating_mode="tolerant_v1")
    state, _, repo, gateway, counter = state_for_extraction(text, settings=settings)
    gateway.outcomes = [extract_every_unit_v2, judge_all]
    with execution_session(state["run_id"], "owner"):
        state.update(claim_extract_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                        claim_extraction_counter=counter))
        gateway.outcomes = [judge_all]
        state.update(claim_judge_node(state, llm_gateway=gateway, claim_extraction_repository=repo,
                                      claim_extraction_counter=counter))
        state.update(claim_decide_node(state))
    claim = ClaimRecord.model_validate(state["extracted_claims"][0])
    assert text[claim.source_start:claim.source_end] == claim.source_text
    serialized = claim.model_dump(mode="json")
    assert "source_locating" not in json.dumps(serialized)
    assert "location_diagnostics" not in json.dumps(serialized)
    assert "rules_hash" not in json.dumps(serialized)
    # The private diagnostics remain in the durable ledger, not the public DTO.
    snapshot = repo.get(state["run_id"])
    result = next(iter(snapshot.state.results.values()))
    assert result.location_diagnostics is not None
    assert isinstance(snapshot.policy.source_locating, SourceLocatingPolicy)
