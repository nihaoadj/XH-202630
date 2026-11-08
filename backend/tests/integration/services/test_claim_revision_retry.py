"""Estimate-version retry acceptance and Claim envelope import/remap (T46)."""

from __future__ import annotations

import json
from copy import deepcopy

import pytest

from app.agents.resource_workflows.learning_documents.revision_inputs import (
    build_claim_review_revision_input,
    pack_revision_input,
    unpack_revision_input,
)
from app.agents.resource_workflows.learning_documents.resource_retry import reuse_resource_context_node
from app.agents.resource_workflows.learning_documents.spec_builder import build_resource_specs
from app.models.generation.dispatch import (
    ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION,
    ESTIMATE_TEXT_WORKFLOW_VERSION,
)
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile, LearningResource
from app.models.reviews.claims import ClaimVerdict
from app.models.reviews.revision_inputs import ClaimReviewRevisionInput
from app.models.shared.persistence import PersistedEvidenceSnapshot, canonical_hash
from app.services.generation.generation import build_workflow_state
from tests.fakes.evidence import make_evidence
from tests.fixtures.claim_revision.targeted_v1.synthetic import make_claim, make_judgement
from tests.unit.services.test_resource_retry_service import prepare, source_state


@pytest.fixture(autouse=True)
def _freeze_legacy_review_strategies(monkeypatch):
    # ``source_state`` builds the legacy TEXT-workflow dispatch; pin the same
    # strategies the historical snapshots were built for so the T45 defaults
    # (neutral claim + resource_issue) never leak into these fixtures.
    from app.config import Settings
    legacy = Settings(claim_extraction_strategy="legacy_v3", resource_review_strategy="compat")
    monkeypatch.setattr("app.services.generation.jobs.get_settings", lambda: legacy)


@pytest.fixture
def source():
    return source_state()


@pytest.mark.parametrize("version", [ESTIMATE_TEXT_WORKFLOW_VERSION, ESTIMATE_RESOURCE_RETRY_WORKFLOW_VERSION])
def test_estimate_version_without_frozen_policy_is_rejected(source, version):
    from app.core.security.errors import ApplicationError
    source.repo._dispatch_metadata["source"]["dispatch_snapshot"]["workflow_version"] = version
    with pytest.raises(ApplicationError):
        prepare(source)


def test_valid_estimate_source_version_is_accepted(source):
    from app.agents.resource_workflows.learning_documents.claim_extraction.budget import freeze_policy
    from app.core.llm.counting import CharacterEstimator
    from tests.fakes.claim_extraction import NeutralScriptedGateway, neutral_settings
    from app.models.reviews.claim_extraction import digest
    snapshot = source.repo._dispatch_metadata["source"]["dispatch_snapshot"]
    policy = freeze_policy(neutral_settings(), NeutralScriptedGateway([]), CharacterEstimator())
    snapshot.update(workflow_version=ESTIMATE_TEXT_WORKFLOW_VERSION,
        claim_extraction_mode=policy.strategy, claim_extraction_policy=policy.model_dump(mode="json"),
        claim_extraction_policy_hash=digest(policy))
    assert prepare(source).source_run_id == "source"


def _claim_retry_state():
    evidence = [make_evidence(evidence_id="old-0", chunk_id="chunk-0", rank=1)]
    spec = build_resource_specs(
        run_id="old-run", resource_types=["讲义"], topic="冻结主题", difficulty="初级",
        learning_plan={}, evidence=evidence, target_skill_nodes=["node"],
        node_evidence_map={"node": [item.evidence_id for item in evidence]},
    )[0]
    old = LearningResource(
        resource_id="old-resource", run_id="old-run", learner_id="learner", resource_type="讲义",
        resource_spec_id=spec.resource_spec_id, resource_family_id=spec.resource_family_id,
        difficulty="初级", content_text="原句。", knowledge_points=["node"], source_refs=[], version=1,
    )
    claim = make_claim(seed="a", resource_id="old-resource", resource_version=1, claim_text="错误断言",
                       source_text="原句", source_start=0, source_end=2)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.CONTRADICTED, evidence_ids=["old-0"])
    claim_input = build_claim_review_revision_input(
        resource_spec_id=spec.resource_spec_id, resource=old, targets=["node"],
        claims=[claim], judgements=[judgement], evidence=evidence,
    )
    context = dict(
        schema_version="1.0", source_run_id="old-run", source_spec_id=spec.resource_spec_id,
        source_checkpoint_hash="a" * 64, diagnosis={"frozen": "diagnosis"}, learning_plan={"frozen": "plan"},
        spec=spec.model_dump(mode="json"),
        evidence=[PersistedEvidenceSnapshot.from_evidence(item, run_id="old-run", retrieval_step_id="old-retrieve").model_dump(mode="json") for item in evidence],
        query_texts={evidence[0].evidence_id: evidence[0].query},
        evidence_allocation=None,
        retrieval_strategy_version="legacy", retrieval_config_hash="2" * 64,
        source_resource=old.model_dump(mode="json"),
        revision_feedback=pack_revision_input(claim_input),
    )
    context["context_hash"] = canonical_hash(context)
    learner = LearnerProfile(learner_id="learner", learner_type="初学者", education="本科", major="计算机", learning_goal="学习")
    request = GenerateRequest(learner_id="learner", topic="冻结主题", knowledge_base_id="kb-fixture", resource_types=["讲义"], include_review=True)
    state = build_workflow_state(learner, request, run_id="new-run")
    state["target_skill_nodes"] = ["node"]
    state["resource_retry_context"] = context
    return state, claim_input


def test_claim_envelope_remaps_identifiers_but_preserves_content():
    state, original = _claim_retry_state()
    before = deepcopy(state["resource_retry_context"])
    result = reuse_resource_context_node(state)
    new_spec_id = result["resource_specs"][0]["resource_spec_id"]
    assert state["resource_retry_context"] == before

    envelope = result["constraints"]["generation_revision_inputs"][new_spec_id]
    remapped = unpack_revision_input(envelope)
    assert isinstance(remapped, ClaimReviewRevisionInput)
    # Content stays verbatim; only identifiers are rebased.
    assert remapped.problems[0].claim_text == "错误断言"
    assert remapped.spans[0].source_text == "原句"
    assert remapped.problems[0].reason == "合成判定理由"
    # The resource spec id is rebased to the new run; the parent identity stays.
    assert remapped.resource_spec_id == new_spec_id
    assert remapped.parent_resource_id == "old-resource"
    # Judge evidence id is remapped to the cloned evidence id, never the source.
    cloned_evidence_ids = [item.evidence_id for item in result["retrieved_evidence"]]
    assert remapped.problems[0].evidence_ids != ["old-0"]
    assert remapped.problems[0].evidence_ids == [cloned_evidence_ids[0]]
    # The legacy mixed slot is replaced, not duplicated.
    assert "revision_feedback" not in result["constraints"]


def test_legacy_revision_feedback_path_still_works():
    state, _ = _claim_retry_state()
    # Replace the envelope with the legacy feedback dict shape.
    context = state["resource_retry_context"]
    context["revision_feedback"] = {"issues": [{"resource_type": "讲义", "evidence_ids": ["old-0"]}]}
    context["context_hash"] = canonical_hash({key: value for key, value in context.items() if key != "context_hash"})
    result = reuse_resource_context_node(state)
    assert "generation_revision_inputs" not in result["constraints"]
    assert result["constraints"]["revision_feedback"]["issues"][0]["evidence_ids"] != ["old-0"]


def test_claim_only_review_feedback_builds_claim_input():
    from types import SimpleNamespace
    from app.services.generation.resource_retry import _retry_revision_input
    state, original = _claim_retry_state()
    resource = LearningResource.model_validate(state["resource_retry_context"]["source_resource"])
    claim = make_claim(seed="a", resource_id=resource.resource_id, resource_version=1,
        claim_text="错误", source_text="原句", source_start=0, source_end=2)
    judgement = make_judgement(claim=claim, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[])
    generation = SimpleNamespace(claim_repo=SimpleNamespace(
        list_claims_by_run=lambda _: [claim], list_judgements_by_run=lambda _: [judgement]))
    feedback = {"issues": [{"claim_ids": [claim.claim_id]}],
        "revision_instructions": [{"target_claim_ids": [claim.claim_id]}]}
    result = _retry_revision_input(generation=generation, run_id="old-run", resource=resource,
        spec_id=original.resource_spec_id, spec=SimpleNamespace(knowledge_points=["node"]),
        feedback=feedback, evidence=[])
    assert result["kind"] == "claim"
    assert len(result["input"]["problems"]) == 1


def test_unknown_envelope_is_not_imported_as_legacy():
    state, _ = _claim_retry_state()
    context = state["resource_retry_context"]
    context["revision_feedback"]["schema_version"] = "revision-input-future"
    context["context_hash"] = canonical_hash({k: v for k, v in context.items() if k != "context_hash"})
    with pytest.raises(Exception):
        reuse_resource_context_node(state)


def test_prepare_service_routes_aggregate_claim_failure_to_claim_envelope(source):
    from types import SimpleNamespace
    s = source
    parent = s.resources.get("parent")
    claim = make_claim(seed="service", resource_id="parent", source_text="old draft", source_start=0, source_end=9)
    judge = make_judgement(claim=claim, verdict=ClaimVerdict.NOT_IN_EVIDENCE, evidence_ids=[])
    s.generation.claim_repo = SimpleNamespace(list_claims_by_run=lambda _: [claim],
        list_judgements_by_run=lambda _: [judge])
    s.audit.list_reviews_by_run = lambda _: [{"resource_id": "parent", "decision": "approve"}]
    projection = dict(s.checkpoint.state_projection)
    projection["review"] = {"issues": [{"resource_id": "parent", "claim_ids": [claim.claim_id]}],
        "revision_instructions": [{"target_resource_type": parent.resource_type, "target_claim_ids": [claim.claim_id]}]}
    s.checkpoint = s.checkpoint.model_copy(update={"state_projection": projection, "state_hash": canonical_hash(projection)})
    context = prepare(s)
    assert context.revision_feedback["kind"] == "claim"
    assert context.revision_feedback["input"]["spans"][0]["source_text"] == "old draft"
