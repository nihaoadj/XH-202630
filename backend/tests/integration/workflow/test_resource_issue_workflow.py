"""Workflow routing and targeted revision preparation for the resource loop (T44 P3/P5)."""

from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.workflow import (
    _prepare_revision_node,
    route_after_review,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceReviewBindingV1,
    ResourceReviewInitialV1,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import text_hash
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.lecture import LectureAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.ledger import append_model_observation_v1


def _policy():
    return ResourceReviewPolicyV1(context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2)


def _resource():
    return LearningResource.model_validate({
        "resource_id": "res-1", "resource_type": "讲义", "difficulty": "初级",
        "content_text": "## 标题\n讲解内容。", "resource_spec_id": "spec-1", "resource_family_id": "fam-1",
        "version": 1, "parent_resource_id": None, "knowledge_points": ["目标一"],
        "source_refs": [], "storage_type": "text",
    })


def _ledger():
    policy = _policy()
    material = LectureAdapter().build_material(resource=_resource(), evidence=[], spec=None, targets=["目标一"])
    binding = ResourceReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="fam-1", resource_id="res-1",
        resource_type="讲义", version=1, text_exact_hash=material.text_exact_hash,
        structured_payload_hash=None, artifact_exact_hash=material.artifact_exact_hash,
        comparison_hash=material.comparison_hash, evidence_snapshot_hash=text_hash("evidence"),
        policy_hash=policy_hash(policy))
    issue = ResourceIssueV1.model_validate({
        "issue_id": "tmp-1", "code": "self_contained_gap", "severity": "high", "blocking": True,
        "blocking_rule": "self_contained", "dimension": "self_contained",
        "location": {"kind": "root"}, "impact": "x", "requirement": "y", "acceptance": "z",
        "criteria_version": 1, "path": "reorganize_existing", "teaching_rule_id": "self_contained",
        "executability": "executable", "rationale": "r"})
    output = ResourceReviewInitialV1.model_validate({
        "binding": binding.model_dump(mode="json"),
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "fail"},
        "targets": [{"target": "目标一", "status": "covered", "reason": "已讲解", "location": {"kind": "root"}}],
        "hallucination_score": 0.1, "issues": [issue.model_dump(mode="json")],
        "omitted_blocking_issues": False,
    })
    return append_model_observation_v1(
        previous=None, binding=binding, step_id="step-1", output=output, material=material,
        adapter=LectureAdapter(), parent_text=None, parent_comparison_hash=None)


def _state(*, claim_only: bool = False):
    policy = _policy()
    resource = _resource()
    ledger = _ledger()
    instruction = {"target_resource_type": "讲义", "resource_spec_id": "spec-1",
                   "action": "修复", "priority": 1}
    if claim_only:
        instruction["target_claim_ids"] = ["claim-1"]
    return {
        "run_id": "run-1", "trace": [], "generation_attempt": 1, "revision_count": 0,
        "claim_revision_count": 0, "max_iterations": 2, "claim_max_iterations": 1,
        "resource_review_policy": policy.model_dump(mode="json"),
        "resource_review_policy_hash": policy_hash(policy),
        "resource_review_contract_version": "1.0",
        "resource_specs": [{"resource_spec_id": "spec-1", "resource_family_id": "fam-1",
                            "knowledge_points": ["目标一"], "difficulty": "初级"}],
        "generated_resources": [resource],
        "resource_ledgers": {"spec-1": ledger.model_dump(mode="json")},
        "resource_review_results": {"res-1": {"decision": "revise", "resource_type": "讲义",
                                              "resource_spec_id": "spec-1"}},
        "resource_executions": [{"resource_id": "res-1", "resource_spec_id": "spec-1",
                                 "resource_type": "讲义", "validation_status": "pending"}],
        "review_result": {"decision": "revise", "suggestion": "需要修复",
                          "issues": [], "revision_instructions": [instruction]},
        "constraints": {}, "target_skill_nodes": [],
    }


def test_prepare_revision_builds_resource_work_order():
    state = _state()
    result = _prepare_revision_node(state, claim_only=False)
    assert "resource_revision" in result
    order = result["resource_revision"]["spec-1"]
    assert order["resource_spec_id"] == "spec-1"
    assert order["parent_resource_id"] == "res-1"
    assert len(order["open_issues"]) == 1
    assert order["claim_only"] is False
    # Only the selected spec is marked for revision.
    revised = [r for r in result["generated_resources"] if r.review_status == "revision_requested"]
    assert [r.resource_spec_id for r in revised] == ["spec-1"]


def test_claim_only_revision_marks_claim_kind():
    state = _state(claim_only=True)
    result = _prepare_revision_node(state, claim_only=True)
    order = result["resource_revision"]["spec-1"]
    assert order["claim_only"] is True
    assert order["revision_kind"] == "claim"


def test_route_after_review_revises_when_under_budget():
    state = _state()
    assert route_after_review(state) == "prepare_revision"
