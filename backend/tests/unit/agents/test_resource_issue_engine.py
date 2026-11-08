from app.models.reviews.resource_review_policy import execution_identity_fields
"""Engine-level tests for the generic resource review loop (T44 P2/P4).

The gateway is a scripted fake: it echoes the frozen binding back and returns a
clean approve, so the engine's full freeze -> gate -> call -> validate -> commit
path is exercised deterministically (zero real model calls).
"""

import json

from types import SimpleNamespace

import pytest


from app.agents.resource_workflows.learning_documents.reviewing import ReviewCallCollector
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.engine import review_resource_v1
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash
from app.models.shared.llm import LLMCallContext
from tests.fakes.llm import ScriptedLLMGateway


def _resource(resource_type="讲义", *, content="## 标题\n讲解内容。", **extra):
    base = dict(resource_id="res-1", resource_type=resource_type, difficulty="初级",
                content_text=content, resource_spec_id="spec-1", resource_family_id="fam-1",
                version=1, parent_resource_id=None, knowledge_points=["目标一"],
                practice_guide_payload=None, assessment_payload=None, review_practice_payload=None,
                source_refs=[], storage_type="text")
    base.update(extra)
    return LearningResource.model_validate(base)


def _policy():
    return ResourceReviewPolicyV1(context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2)


def _state(policy, resource):
    return {
        "run_id": "run-1",
        "resource_review_policy": policy.model_dump(mode="json"),
        "resource_review_policy_hash": policy_hash(policy),
        "resource_review_contract_version": "1.1",
        **execution_identity_fields("fake-model"),
        "resource_specs": [{"resource_spec_id": "spec-1", "resource_family_id": "fam-1",
                            "knowledge_points": ["目标一"], "difficulty": "初级"}],
        "resource_ledgers": {},
        "resource_revision": {},
        "revision_count": 0,
        "max_iterations": 2,
        "generated_resources": [resource],
    }


def _approve_outcome(kwargs):
    """Echo the frozen binding and produce a clean, fully-covered approve."""
    human = kwargs["messages"][1]
    payload = json.loads(human.content)
    binding = payload["binding"]
    targets = payload["targets"]
    return {
        "binding": binding,
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": t, "status": "covered", "reason": "已讲解", "location": {"kind": "root"}}
                    for t in targets],
        "hallucination_score": 0.0,
        "issues": [],
        "omitted_blocking_issues": False,
    }


def _run(resource=None, *, outcomes=None, policy=None):
    policy = policy or _policy()
    resource = resource or _resource()
    gateway = ScriptedLLMGateway(outcomes if outcomes is not None else [_approve_outcome])
    collector = ReviewCallCollector()
    context = LLMCallContext(run_id="run-1", step_id="step-1", node_name="reviewer",
                             schema_name="ResourceReviewInitialV1", generation_attempt=1)
    outcome = review_resource_v1(
        state=_state(policy, resource), resource=resource, evidence=[],
        step_id="step-1", context=context, gateway=gateway, collector=collector,
        review_id="rev-1", step_guard=lambda **kw: None)
    return outcome, gateway, collector


def test_clean_lecture_initial_review_approves():
    outcome, gateway, collector = _run()
    assert outcome.ledger is not None
    assert outcome.ledger.observations[-1].decision == "approve"
    assert outcome.raw["decision"] == "approve"
    # One logical model call, one model-origin observation.
    assert len(gateway.calls) == 1
    assert len(outcome.ledger.observations) == 1
    assert outcome.ledger.observations[-1].origin == "model_review"
    assert outcome.stop_reason is None


def test_program_gate_failure_skips_model_and_blocks():
    # A structured resource without its required payload fails the projection gate.
    resource = _resource("实操指南", content="# 实操\n内容")
    resource = resource.model_copy(update={"practice_guide_payload": None})
    outcome, gateway, collector = _run(resource=resource, outcomes=[])
    assert outcome.ledger is not None
    assert outcome.ledger.observations[-1].origin == "program_gate"
    assert outcome.stop_reason == "program_gate_failed"
    # Zero semantic calls were made.
    assert len(gateway.calls) == 0
    assert outcome.raw["decision"] == "revise"


def test_practice_review_builds_structured_material():
    from tests.fakes.resource_reviews import case
    sample = case("practice.clean.01")
    resource = LearningResource.model_validate(sample["resource"]).model_copy(update={
        "resource_spec_id": "spec-1", "resource_family_id": "fam-1", "version": 1})
    outcome, gateway, collector = _run(resource=resource)
    assert outcome.ledger is not None
    assert outcome.ledger.observations[-1].decision == "approve"
    assert outcome.ledger.binding.structured_payload_hash is not None


def test_recheck_uses_recheck_profile_and_appends_observation():
    policy = _policy()
    resource_v1 = _resource()
    first, _, _ = _run(resource=resource_v1, policy=policy)
    assert first.ledger.observations[-1].decision == "approve"
    # Second round: version 2 with the parent ledger present forces the recheck path.
    resource_v2 = resource_v1.model_copy(update={"version": 2, "resource_id": "res-2",
                                                 "parent_resource_id": "res-1"})
    state = _state(policy, resource_v2)
    state["resource_ledgers"] = {"spec-1": first.ledger.model_dump(mode="json")}
    state["resource_revision"] = {"spec-1": {"previous_text": resource_v1.content_text}}
    gateway = ScriptedLLMGateway([_approve_outcome])
    collector = ReviewCallCollector()
    context = LLMCallContext(run_id="run-1", step_id="step-2", node_name="reviewer",
                             schema_name="ResourceReviewRecheckV1", generation_attempt=2)
    outcome = review_resource_v1(
        state=state, resource=resource_v2, evidence=[], step_id="step-2", context=context,
        gateway=gateway, collector=collector, review_id="rev-2", step_guard=lambda **kw: None)
    assert outcome.ledger is not None
    assert len(outcome.ledger.observations) == 2
    assert gateway.calls[0]["context"].schema_name == "ResourceReviewRecheckV1"

def test_location_prompt_examples_match_the_strict_location_contract():
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.prompts.common import OUTPUT_RULES
    from app.models.reviews.resource_review import ResourceLocationV1
    import re
    examples = re.findall(r"<location_example>(.*?)</location_example>", OUTPUT_RULES.text)
    assert len(examples) == 3
    assert {ResourceLocationV1.model_validate_json(value).kind for value in examples} == {
        "structured", "paragraph", "root"}
