"""Workflow prepare/generator routing of the two generation revision inputs (T46)."""

from __future__ import annotations

from app.agents.resource_workflows.learning_documents.revision_inputs import unpack_revision_input
from app.agents.resource_workflows.learning_documents.workflow import _prepare_revision_node
from app.models.reviews.claims import ClaimVerdict
from app.models.reviews.revision_inputs import (
    CLAIM_KIND,
    ClaimReviewRevisionInput,
    ORDINARY_KIND,
    ResourceReviewRevisionInput,
)
from tests.fakes.evidence import make_evidence
from tests.fixtures.claim_revision.targeted_v1.synthetic import (
    make_claim,
    make_judgement,
    make_resource,
)

SPEC_ID = "33333333-3333-3333-3333-333333333333"


def _state(*, claim_only, resources, claims=None, judgements=None, evidence=None, review_result=None):
    instructions = review_result["revision_instructions"] if review_result else []
    targets = {item["target_resource_type"] for item in instructions if item.get("target_resource_type")}
    return {
        "run_id": "run",
        "schema_version": "1.0",
        "revision_count": 0,
        "claim_revision_count": 0,
        "generation_attempt": 1,
        "review_result": review_result or {},
        "resource_specs": [
            {"resource_spec_id": item.resource_spec_id, "knowledge_points": list(item.knowledge_points),
             "resource_family_id": "11111111-1111-1111-1111-111111111111", "resource_type": item.resource_type,
             "learning_objective": "synthetic", "evidence_ids": [e.evidence_id for e in (evidence or [])] or ["unused"],
             "difficulty": item.difficulty, "representations": [{"representation": "text", "max_output_tokens": 1024}],
             "display_order": 1}
            for item in resources
        ],
        "generated_resources": list(resources),
        "extracted_claims": [item.model_dump(mode="json") for item in (claims or [])],
        "claim_judgements": [item.model_dump(mode="json") for item in (judgements or [])],
        "retrieved_evidence": list(evidence or []),
        "resource_executions": [],
        "resource_review_results": {},
        "constraints": {},
        "trace": [],
        "targets": sorted(targets),
    }


def test_claim_only_prepare_builds_claim_input_before_clearing_claims():
    resource = make_resource(resource_id="parent", resource_spec_id=SPEC_ID, resource_type="讲义", content_text="原句在正文。")
    claim = make_claim(seed="a", resource_id="parent", resource_version=1, claim_text="错误断言",
                       source_text="原句在正文", source_start=0, source_end=5)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"])
    evidence = [make_evidence(evidence_id="evidence", chunk_id="chunk")]
    review_result = {
        "revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [claim.claim_id]}],
        "issues": [{"claim_ids": [claim.claim_id], "resource_type": "讲义"}],
    }
    state = _state(claim_only=True, resources=[resource], claims=[claim], judgements=[judgement], evidence=evidence, review_result=review_result)

    result = _prepare_revision_node(state, claim_only=True)

    envelope = result["constraints"]["generation_revision_inputs"][SPEC_ID]
    model = unpack_revision_input(envelope)
    assert isinstance(model, ClaimReviewRevisionInput)
    assert envelope["kind"] == CLAIM_KIND
    problem = model.problems[0]
    assert problem.claim_text == "错误断言"
    assert problem.source_span_id and model.spans[0].source_text == "原句在正文"
    assert problem.reason == "合成判定理由"
    assert problem.verdict == "contradicted"
    # The claims/judgements are cleared only after the input is materialised.
    assert result["extracted_claims"] == [] and result["claim_judgements"] == []


def test_claim_only_prepare_with_no_bad_claim_emits_no_input():
    resource = make_resource(resource_id="parent", resource_spec_id=SPEC_ID, resource_type="讲义")
    claim = make_claim(seed="a", resource_id="parent", resource_version=1, claim_text="好断言", source_text="原句", source_start=0, source_end=2)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.SUPPORTED, evidence_ids=["evidence"])
    review_result = {"revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [claim.claim_id]}]}
    state = _state(claim_only=True, resources=[resource], claims=[claim], judgements=[judgement], evidence=[make_evidence(evidence_id="evidence")], review_result=review_result)

    result = _prepare_revision_node(state, claim_only=True)

    assert "generation_revision_inputs" not in result["constraints"]


def test_ordinary_prepare_builds_ordinary_input_from_compat_feedback():
    resource = make_resource(resource_id="parent", resource_spec_id=SPEC_ID, resource_type="讲义", content_text="旧正文")
    review_result = {
        "revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [], "action": "修"}],
        "issues": [{"resource_type": "讲义", "message": "修这个问题"}],
        "suggestion": "改一下",
    }
    state = _state(claim_only=False, resources=[resource], review_result=review_result)

    result = _prepare_revision_node(state, claim_only=False)

    envelope = result["constraints"]["generation_revision_inputs"][SPEC_ID]
    model = unpack_revision_input(envelope)
    assert envelope["kind"] == ORDINARY_KIND
    assert isinstance(model, ResourceReviewRevisionInput)
    assert model.feedback["issues"] == [{"resource_type": "讲义", "message": "修这个问题"}]
    assert model.previous_text == "旧正文"


def test_sibling_spec_without_bad_claim_never_receives_foreign_input():
    claimed = make_resource(resource_id="parent-a", resource_spec_id="aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa", resource_type="讲义", content_text="原句。")
    clean = make_resource(resource_id="parent-b", resource_spec_id="bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb", resource_type="讲义", content_text="另一段。")
    claim = make_claim(seed="a", resource_id="parent-a", resource_version=1, claim_text="错", source_text="原句", source_start=0, source_end=2)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"])
    review_result = {"revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [claim.claim_id]}]}
    state = _state(claim_only=True, resources=[claimed, clean], claims=[claim], judgements=[judgement],
                   evidence=[make_evidence(evidence_id="evidence")], review_result=review_result)

    result = _prepare_revision_node(state, claim_only=True)

    inputs = result["constraints"]["generation_revision_inputs"]
    assert set(inputs) == {claimed.resource_spec_id}
    assert clean.resource_spec_id not in inputs


def test_ordinary_claim_ordinary_rounds_carry_exactly_one_kind_each():
    resource = make_resource(resource_id="parent", resource_spec_id=SPEC_ID, resource_type="讲义", content_text="原句。")
    claim = make_claim(seed="a", resource_id="parent", resource_version=1, claim_text="错", source_text="原句", source_start=0, source_end=2)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["evidence"])
    claim_review = {"revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [claim.claim_id]}]}
    ordinary_review = {"revision_instructions": [{"target_resource_type": "讲义", "target_claim_ids": [], "action": "修"}]}

    claim_state = _state(claim_only=True, resources=[resource], claims=[claim], judgements=[judgement],
                         evidence=[make_evidence(evidence_id="evidence")], review_result=claim_review)
    claim_result = _prepare_revision_node(claim_state, claim_only=True)
    assert unpack_revision_input(claim_result["constraints"]["generation_revision_inputs"][SPEC_ID]).kind == CLAIM_KIND

    ordinary_state = _state(claim_only=False, resources=[resource], review_result=ordinary_review)
    ordinary_result = _prepare_revision_node(ordinary_state, claim_only=False)
    assert unpack_revision_input(ordinary_result["constraints"]["generation_revision_inputs"][SPEC_ID]).kind == ORDINARY_KIND


def test_claim_prepare_only_passes_spec_evidence_to_actual_prompt():
    from app.agents.resource_agents.text import TextResourceAgent
    from app.models.shared.agent_contracts import ResourceGenerationContext, ResourceSpec
    resource = make_resource(resource_id="parent", resource_spec_id=SPEC_ID, content_text="fact")
    claim = make_claim(seed="scope", resource_id="parent", source_text="fact", source_start=0, source_end=4)
    judge = make_judgement(claim=claim, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[])
    own, other = make_evidence(evidence_id="own"), make_evidence(evidence_id="foreign")
    state = _state(claim_only=True, resources=[resource], claims=[claim], judgements=[judge],
        evidence=[own, other], review_result={"revision_instructions": [
            {"target_resource_type": resource.resource_type, "target_claim_ids": [claim.claim_id]}]})
    state["resource_specs"][0]["evidence_ids"] = ["own"]
    result = _prepare_revision_node(state, claim_only=True)
    model = unpack_revision_input(result["constraints"]["generation_revision_inputs"][SPEC_ID])
    spec = ResourceSpec.model_validate(state["resource_specs"][0])
    context = ResourceGenerationContext(run_id="run", batch_id="batch", topic="synthetic", evidence=[own],
        constraints={}, claim_review_revision=model)
    payload = TextResourceAgent().common_prompt_payload(spec, context)
    assert [e["evidence_id"] for e in payload["claim_review_revision"]["evidence"]] == ["own"]
    assert "foreign" not in str(payload)
