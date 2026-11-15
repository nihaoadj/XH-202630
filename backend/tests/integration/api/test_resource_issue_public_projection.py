"""Public projection boundary: the private audit never leaks into public traces (T44 P6)."""

from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.decisions import (
    derive_decision,
    project_public_summary,
)
from app.models.reviews.review_audit import PRIVATE_REVIEW_FIELDS, public_review_payload
from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceReviewInitialV1,
)


def _issue(severity="high", dimension="factual_evidence", *, evidence=False):
    data = {
        "issue_id": "tmp-1", "code": "factual_error", "severity": severity, "blocking": True,
        "blocking_rule": "factual_evidence", "dimension": dimension,
        "location": {"kind": "root"}, "impact": "秘密影响", "requirement": "秘密要求",
        "acceptance": "秘密验收", "criteria_version": 1, "path": "reorganize_existing",
        "rationale": "秘密理由",
    }
    if evidence:
        data["path"] = "add_from_evidence"
        data["evidence_refs"] = [{"evidence_id": "e1", "excerpt_hash": "a" * 64}]
    else:
        data["teaching_rule_id"] = "factual_evidence"
    data["executability"] = "executable"
    return ResourceIssueV1.model_validate(data)


def _output(issues=()):
    return ResourceReviewInitialV1.model_validate({
        "binding": {
            "run_id": "run-1", "resource_spec_id": "spec-1", "lineage_id": "fam-1",
            "resource_id": "res-1", "resource_type": "讲义", "version": 1,
            "text_exact_hash": "a" * 64, "structured_payload_hash": None,
            "artifact_exact_hash": "b" * 64, "comparison_hash": "c" * 64,
            "evidence_snapshot_hash": "d" * 64, "policy_hash": "e" * 64,
        },
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": "目标一", "status": "covered", "reason": "秘密理由", "location": {"kind": "root"}}],
        "hallucination_score": 0.0,
        "issues": [i.model_dump(mode="json") for i in issues],
        "omitted_blocking_issues": False,
    })


def _material():
    from types import SimpleNamespace
    from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import ResourceMaterial, LocationIndex
    return ResourceMaterial(
        resource_type="讲义", text="正文", structured_payload=None, text_exact_hash="a" * 64,
        structured_payload_hash=None, artifact_exact_hash="b" * 64, comparison_hash="c" * 64,
        comparison_projection=None, presentation_comparison=None, index=LocationIndex(root_allowed=True),
        targets=("目标一",), evidence_hashes={}, difficulty="初级", rule_ids=())


def test_public_summary_never_copies_model_rationale():
    issue = _issue()
    summary = project_public_summary(
        decision="revise", output=_output([issue]), material=_material(),
        resource_id="res-1", resource_spec_id="spec-1", open_issues=(issue,))
    assert len(summary["issues"]) <= 3
    assert len(summary["revision_instructions"]) == 1
    blob = str(summary)
    for secret in ("秘密影响", "秘密要求", "秘密验收", "秘密理由"):
        assert secret not in blob
    # The public issue code is bounded, never the model's free-form code.
    assert summary["issues"][0]["code"] == "factual_risk"


def test_public_summary_caps_issues_at_three():
    issues = [_issue(severity="high", dimension="self_contained") for _ in range(5)]
    summary = project_public_summary(
        decision="revise", output=_output(issues), material=_material(),
        resource_id="res-1", resource_spec_id="spec-1", open_issues=tuple(issues))
    assert len(summary["issues"]) == 3


def test_derive_decision_evidence_insufficient_is_human_review():
    issue = _issue()
    decision = derive_decision(open_issues=(issue,), dimensions_pass=False, coverage_rate=1.0,
                               unchanged=False, consecutive_unchanged=0, coverage_threshold=0.8,
                               max_consecutive_unchanged=2)
    assert decision == "revise"


def test_private_fields_cover_v4_resource_namespace():
    assert "review_audit_v4" in PRIVATE_REVIEW_FIELDS
    assert "resource_review_policy" in PRIVATE_REVIEW_FIELDS
    assert "resource_ledgers" in PRIVATE_REVIEW_FIELDS
    assert "resource_review_identity" in PRIVATE_REVIEW_FIELDS
    assert "resource_review_identity_hash" in PRIVATE_REVIEW_FIELDS
    payload = public_review_payload({
        "review_audit_v4": {"secret": 1}, "resource_ledgers": {"secret": 2},
        "resource_review_identity": {"model_name": "private-model"},
        "resource_review_identity_hash": "private-hash",
        "review": {"decision": "approve"},
    })
    assert "review_audit_v4" not in payload
    assert "resource_ledgers" not in payload
    assert payload == {"review": {"decision": "approve"}}
