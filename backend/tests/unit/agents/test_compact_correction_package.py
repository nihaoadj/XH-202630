"""Two-exercise content and display-only Claim boundary, with V1 compatibility."""

import copy
import json

import pytest
from pydantic import ValidationError

from app.agents.resource_agents.correction_package import (
    CorrectionTrainingPackageAgent, STRUCTURED_CONTRACT_KEY, structured_generation_contract,
)
from app.core.learning_documents.correction_package import render_correction_markdown, correction_audit_source
from app.models.learning_documents.correction_package import (
    CorrectionPackageContentV2, assemble_compact_correction_package, parse_correction_package,
)
from app.agents.resource_workflows.learning_documents.claim_extraction import compact_correction_sources as compact
from app.agents.resource_workflows.learning_documents.claim_extraction.resource_sources import build_source, source_for_claims
from app.models.reviews.claim_extraction import digest
from app.models.reviews.claims import ClaimRecord, ClaimJudgement
from tests.unit.agents.test_structured_correction_package import content, package, structured_inputs
from tests.fakes.llm import ScriptedLLMGateway
from tests.fakes.claim_extraction import prepare_ledger
from tests.integration.workflow.test_structured_correction_package import setup_source, extract_and_judge


def compact_content():
    body = content()
    body["unit"].pop("worked_example")
    body["unit"]["exercises"].pop("similar")
    return body


def compact_package():
    return assemble_compact_correction_package(content=compact_content(), title="双练习纠错包",
        target=dict(node_id="k", node_name="编码契约", mastery_status="weak", failed_dimensions=["concept_application"]),
        run_id="run-test", focus_snapshot_hash="a" * 64)


def compact_source_setup(locating=False):
    state, _, repo, gateway, counter = setup_source(locating)
    p = repo.get(state["run_id"]).policy.model_copy(update={"correction_sources": compact.frozen_extension()})
    audit, repo = prepare_ledger(p=p)
    state.update(claim_extraction_policy=p.model_dump(mode="json"), claim_extraction_policy_hash=digest(p))
    resource = state["generated_resources"][0]; pack = compact_package()
    resource.correction_package_payload = pack.model_dump(mode="json")
    resource.correction_package_payload_hash = pack.payload_hash
    resource.content_text = render_correction_markdown(pack).strip()
    return state, audit, repo, gateway, counter


@pytest.mark.parametrize("damage", ["example", "similar", "missing_guided", "missing_transfer"])
def test_new_schema_requires_exactly_two_exercises_and_rejects_removed_fields(damage):
    body = compact_content()
    if damage == "example": body["unit"]["worked_example"] = content()["unit"]["worked_example"]
    elif damage == "similar": body["unit"]["exercises"]["similar"] = content()["unit"]["exercises"]["similar"]
    else: body["unit"]["exercises"].pop(damage.removeprefix("missing_"))
    with pytest.raises(ValidationError): CorrectionPackageContentV2.model_validate(body)


def test_renderer_keeps_display_sections_and_places_two_answers_at_end():
    new = compact_package(); text = render_correction_markdown(new)
    for label in ("本次强化目标", "当前状态", "失分维度", "薄弱模式概览", "达标标准", "后续复习动作"):
        assert label in text
    assert "完整示例" not in text and "同构练习" not in text
    assert text.index("引导式练习") < text.index("迁移练习") < text.index("参考答案与分层反馈")
    assert "引导式练习参考答案" in text and "迁移练习参考答案" in text
    assert parse_correction_package(new).payload_hash == new.payload_hash
    old = package()
    assert "完整示例" in render_correction_markdown(old) and "同构练习" in render_correction_markdown(old)


def test_new_generation_uses_v2_and_old_contract_still_uses_v1():
    spec, context = structured_inputs()
    old = CorrectionTrainingPackageAgent().generate(spec, context, llm_gateway=ScriptedLLMGateway([content()]))
    assert old.artifact_data["correction_package"]["schema_version"] == "correction-package-v1"
    constraints = copy.deepcopy(context.constraints)
    constraints[STRUCTURED_CONTRACT_KEY] = structured_generation_contract()
    new_context = context.model_copy(update={"constraints": constraints})
    gateway = ScriptedLLMGateway([compact_content()])
    new = CorrectionTrainingPackageAgent().generate(spec, new_context, llm_gateway=gateway)
    pack = parse_correction_package(new.artifact_data["correction_package"])
    assert pack.schema_version == "correction-package-v2" and new.metadata.prompt_version == "correction-json-generation-v2"
    assert gateway.calls[0]["output_schema"] is CorrectionPackageContentV2
    assert "不参加Claim抽取" in gateway.calls[0]["messages"][0].content


def test_display_roots_are_excluded_but_remain_in_ordinary_audit():
    state, _, repo, _, _ = compact_source_setup()
    resource = state["generated_resources"][0]; source = build_source(resource, repo.get(state["run_id"]).policy)
    targets = {f["path"] for f in source.fields}
    assert not any(any(p.startswith(root) for root in compact.DISPLAY_ROOTS) for p in targets)
    excluded = source.snapshot["excluded_fields"]
    assert all(any(f["path"].startswith(root) for f in excluded) for root in compact.DISPLAY_ROOTS)
    assert any(p.endswith("reference_answer") for p in targets)
    assert any("concept_repair" in p for p in targets)
    assert any(p.endswith("scenario") for p in targets)
    assert any(p.startswith("content.layered_feedback") for p in targets) and "content.summary" in targets
    full = correction_audit_source(compact_package())
    assert any(f.path.startswith("content.training_goals") for f in full.fields)
    assert "learning_status" not in source.text and "concept_application" not in source.text


@pytest.mark.parametrize("strategy", ["compat", "resource_issue_v1"])
def test_ordinary_review_still_checks_retained_display_fields(strategy):
    from tests.unit.agents.test_resource_issue_engine import _state, _policy, _approve_outcome
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import review_resource_v1
    from app.agents.resource_workflows.learning_documents.reviewing import ReviewCallCollector
    from app.models.shared.llm import LLMCallContext
    state, _, _, _, _ = compact_source_setup()
    resource = state["generated_resources"][0].model_copy(update={"resource_spec_id": "spec-1", "resource_family_id": "fam-1"})
    if strategy == "resource_issue_v1":
        policy = _policy().model_copy(update={"input_contract": "single_representation_v1"})
        state = _state(policy, resource); state["resource_specs"][0]["knowledge_points"] = ["k"]
        gateway = ScriptedLLMGateway([_approve_outcome])
        result = review_resource_v1(state=state, resource=resource, evidence=[], step_id="s",
            context=LLMCallContext(run_id="run-1", step_id="s", node_name="reviewer", schema_name="ResourceReviewInitialV1"),
            gateway=gateway, collector=ReviewCallCollector(), review_id="review", step_guard=lambda **kw: None)
        assert result.raw["decision"] == "approve"
        payload = gateway.calls[0]["messages"][-1].content
        prompt = gateway.calls[0]["messages"][0].content
        assert "text" not in json.loads(payload)
    else:
        from app.agents.resource_workflows.learning_documents.reviewing.profiles import resolve_review_profile, correction_content_profile
        from app.agents.resource_workflows.learning_documents.reviewing.payloads import build_review_request
        from app.agents.resource_workflows.learning_documents.reviewing.prompts.builder import build_review_prompt
        from app.agents.resource_workflows.learning_documents.reviewing.types import ReviewAuditInput
        profile = correction_content_profile(resolve_review_profile(resource_type=resource.resource_type, phase="content_v2"), compact=True)
        req = build_review_request(profile=profile, prompt_bundle=build_review_prompt(profile=profile), audit_input=ReviewAuditInput(resource=resource))
        payload, prompt = req.messages[-1].content, req.messages[0].content
    for field in ("training_goals", "focus_overview", "mastery_criteria", "next_review_actions"):
        assert field in payload
    assert "普通审核必须检查" in prompt
    assert "learning_status" not in payload


@pytest.mark.parametrize("locating", [False, True])
def test_compact_claims_judge_revision_and_source_reconstruction(locating):
    from app.agents.resource_workflows.learning_documents.revision_inputs import build_claim_review_revision_input
    state, _, repo, gateway, counter = compact_source_setup(locating)
    extract_and_judge(state, repo, gateway, counter, missing=True)
    resource = state["generated_resources"][0]
    claims = [ClaimRecord.model_validate(c) for c in state["extracted_claims"]]
    restored = source_for_claims(resource, claims)
    assert restored.prompt_version == compact.PROMPT_VERSION
    assert all(restored.text[c.source_start:c.source_end] == c.source_text for c in claims)
    assert state["claim_metrics"][resource.resource_id]["not_in_evidence_claim_total"] == 1
    revision = build_claim_review_revision_input(resource_spec_id="spec", resource=resource, targets=["k"],
        claims=claims, judgements=[ClaimJudgement.model_validate(j) for j in state["claim_judgements"]], evidence=state["retrieved_evidence"])
    assert revision.problems and revision.previous_structured_payload == resource.correction_package_payload
    assert revision.previous_text == restored.text


def test_v2_generation_dispatch_roundtrip_and_unknown_schema_rejected():
    from app.models.generation.correction_dispatch import wrap_correction_dispatch, unwrap_correction_dispatch
    for version in ("correction-json-generation-v1", "correction-json-generation-v2"):
        contract = structured_generation_contract(version)
        wrapper = wrap_correction_dispatch({"workflow_version": "legacy"}, contract)
        assert unwrap_correction_dispatch(wrapper)[1] == contract
    bad = compact_package().model_dump(mode="json"); bad["schema_version"] = "unknown"
    with pytest.raises(ValueError): parse_correction_package(bad)
    old_contract = structured_generation_contract("correction-json-generation-v1")
    assert old_contract["schema_hash"] == "36b824a905884fb9e772818510ae9eb5886216fc74fdd669052a34cc5682fd95"
    assert old_contract["prompt_hash"] == "fa03e99117f174ca5ef3b1a4541c3b4dbff171e743f1e34593407c0fe87479a7"


def test_old_claim_source_cannot_silently_adopt_compact_package():
    from app.agents.resource_workflows.learning_documents.claim_extraction import correction_sources, filtered_correction_sources
    state, _, _, _, _ = compact_source_setup()
    resource = state["generated_resources"][0]
    for marker in (correction_sources.PROMPT_VERSION, filtered_correction_sources.PROMPT_VERSION):
        with pytest.raises(ValueError):
            correction_sources.build_source(resource, force=True, prompt_version=marker)


def test_cross_format_parent_is_rejected_before_generation_call():
    from app.core.security.errors import ApplicationError
    spec, context = structured_inputs()
    constraints = copy.deepcopy(context.constraints)
    constraints[STRUCTURED_CONTRACT_KEY] = structured_generation_contract()
    constraints["_correction_parent_package"] = package().model_dump(mode="json")
    gateway = ScriptedLLMGateway([])
    with pytest.raises(ApplicationError):
        CorrectionTrainingPackageAgent().generate(spec, context.model_copy(update={"constraints": constraints}), llm_gateway=gateway)
    assert not gateway.calls


@pytest.mark.parametrize("kind", ["ordinary", "claim"])
def test_compact_revision_preserves_format_state_and_server_binding(kind):
    from app.models.reviews.revision_inputs import ClaimReviewRevisionInput, ResourceReviewRevisionInput
    spec, context = structured_inputs()
    constraints = copy.deepcopy(context.constraints)
    constraints[STRUCTURED_CONTRACT_KEY] = structured_generation_contract()
    context = context.model_copy(update={"constraints": constraints})
    agent = CorrectionTrainingPackageAgent()
    first = agent.generate(spec, context, llm_gateway=ScriptedLLMGateway([compact_content()]))
    parent = first.artifact_data["correction_package"]
    from hashlib import sha256
    base = dict(resource_spec_id=spec.resource_spec_id, parent_resource_id="parent", parent_version=1,
        previous_text=first.content_text, previous_structured_payload=parent, targets=spec.knowledge_points,
        content_hash=sha256(first.content_text.encode()).hexdigest())
    if kind == "claim":
        value = ClaimReviewRevisionInput(**base, problems=[], spans=[], groups=[], evidence=[])
        context = context.model_copy(update={"claim_review_revision": value, "generation_attempt": 2})
    else:
        value = ResourceReviewRevisionInput(**base, issues=[], closed_issues=[],
                                           unchanged=False, revision_source="ordinary")
        context = context.model_copy(update={"resource_review_revision": value, "generation_attempt": 2})
    changed = compact_content(); changed["summary"] = "记录编码条件并核验。"
    artifact = agent.generate(spec, context, llm_gateway=ScriptedLLMGateway([changed]))
    new = artifact.artifact_data["correction_package"]
    assert new["schema_version"] == "correction-package-v2"
    assert new["learning_status"] == parent["learning_status"] and new["provenance"] == parent["provenance"]
