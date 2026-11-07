"""Revision work-order construction and failure-placeholder isolation (T44 P5)."""

from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import text_hash
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.lecture import LectureAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.ledger import append_model_observation_v1
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.revision import (
    ResourceRevisionWorkOrderV1,
    build_revision_work_order,
    failure_placeholder_work_order,
)
from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceReviewBindingV1,
    ResourceReviewInitialV1,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash


def _resource():
    return SimpleNamespace(
        resource_type="讲义", content_text="## 标题\n讲解内容。", difficulty="初级",
        resource_id="res-1", resource_spec_id="spec-1", resource_family_id="fam-1",
        version=1, parent_resource_id=None, practice_guide_payload=None,
        assessment_payload=None, review_practice_payload=None)


def _policy():
    return ResourceReviewPolicyV1(context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2)


def _ledger(with_issue=False):
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
        "executability": "executable", "rationale": "r"}) if with_issue else None
    output = ResourceReviewInitialV1.model_validate({
        "binding": binding.model_dump(mode="json"),
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass",
                       "self_contained": "fail" if with_issue else "pass"},
        "targets": [{"target": "目标一", "status": "covered", "reason": "已讲解", "location": {"kind": "root"}}],
        "hallucination_score": 0.1 if with_issue else 0.0,
        "issues": [issue.model_dump(mode="json")] if with_issue else [],
        "omitted_blocking_issues": False,
    })
    return append_model_observation_v1(
        previous=None, binding=binding, step_id="step-1", output=output, material=material,
        adapter=LectureAdapter(), parent_text=None, parent_comparison_hash=None)


def test_build_revision_work_order_carries_open_and_closed_issues():
    ledger = _ledger(with_issue=True)
    order = build_revision_work_order(resource_spec_id="spec-1", resource=_resource(),
                                      previous=ledger, revision_kind="ordinary", targets=("目标一",))
    assert order.resource_spec_id == "spec-1"
    assert order.parent_binding is not None
    assert order.parent_resource_id == "res-1"
    assert len(order.open_issues) == 1
    assert order.unchanged is False
    assert order.revision_kind == "ordinary"
    assert order.claim_only is False
    assert order.failed_placeholder is False
    # Round-trips through the JSON shape consumed by the workflow/engine.
    data = order.as_dict()
    assert data["claim_only"] is False
    restored = ResourceRevisionWorkOrderV1.from_dict(data)
    assert restored.open_issues[0].issue_id == order.open_issues[0].issue_id


def test_claim_revision_distinguishes_kind():
    ledger = _ledger(with_issue=True)
    order = build_revision_work_order(resource_spec_id="spec-1", resource=_resource(),
                                      previous=ledger, revision_kind="claim", targets=("目标一",))
    assert order.claim_only is True
    assert order.as_dict()["claim_only"] is True


def test_failure_placeholder_is_never_counted_as_repair():
    order = failure_placeholder_work_order(resource_spec_id="spec-1", resource=_resource(),
                                           targets=("目标一",))
    assert order.failed_placeholder is True
    assert order.parent_binding is None
    assert order.open_issues == ()
    assert order.previous_text is None


def test_revision_requires_ledger_or_placeholder():
    with pytest.raises(ValueError):
        build_revision_work_order(resource_spec_id="spec-1", resource=_resource(),
                                  previous=None, revision_kind="ordinary", targets=("目标一",))


@pytest.mark.parametrize("mutation", [{"content_text": "forged parent"}, {"resource_id": "other-resource"}, {"version": 2}])
def test_revision_rejects_mismatched_parent_package(mutation):
    ledger = _ledger(with_issue=True)
    resource = _resource()
    for key, value in mutation.items():
        setattr(resource, key, value)
    with pytest.raises(ValueError, match="revision parent"):
        build_revision_work_order(resource_spec_id="spec-1", resource=resource,
                                  previous=ledger, revision_kind="ordinary", targets=("目标一",))
