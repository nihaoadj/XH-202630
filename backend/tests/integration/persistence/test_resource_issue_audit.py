"""V4 resource-issue audit: versioned namespace, ownership and round-trip.

These are deterministic model/persistence tests; no real model call is made.
They verify the V4 audit coexists with V1-V3, enforces the frozen policy hash and
ledger ownership, and round-trips through the audit envelope without leaking
private fields into public projections.
"""

from types import SimpleNamespace

import pytest

from app.models.reviews.resource_review import (
    ResourceLedgerV1,
    ResourceReviewBindingV1,
    ResourceReviewInitialV1,
)
from app.models.reviews.resource_review_policy import ResourceReviewPolicyV1, policy_hash
from app.models.reviews.review_audit import (
    AUDIT_NAMESPACE,
    AUDIT_V4_NAMESPACE,
    ReviewAuditRecordV1,
    ReviewAuditRecordV4,
    ReviewPolicySnapshotV1,
    ReviewRepairRecordV3,
    ReviewResourceAuditV1,
    ReviewUsageSummaryV1,
    audit_namespace,
    audit_record_model,
    public_review_payload,
    review_audit_envelope,
    select_audit_envelope,
    summarize_review_calls,
)
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import text_hash
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.lecture import LectureAdapter
from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.ledger import (
    append_model_observation_v1,
)
from app.models.shared.llm import LLMUsage


def _policy():
    return ResourceReviewPolicyV1(context_tokens=262144, max_output_tokens=16384, max_physical_attempts=2)


def _material():
    resource = SimpleNamespace(resource_type="讲义", content_text="## 标题\n讲解内容。", difficulty="初级",
                               resource_id="res-1", resource_spec_id="spec-1", resource_family_id="fam-1",
                               version=1, parent_resource_id=None, practice_guide_payload=None,
                               assessment_payload=None, review_practice_payload=None)
    return LectureAdapter().build_material(resource=resource, evidence=[], spec=None, targets=["目标一"])


def _binding(material, policy):
    return ResourceReviewBindingV1(
        run_id="run-1", resource_spec_id="spec-1", lineage_id="fam-1", resource_id="res-1",
        resource_type="讲义", version=1, text_exact_hash=material.text_exact_hash,
        structured_payload_hash=None, artifact_exact_hash=material.artifact_exact_hash,
        comparison_hash=material.comparison_hash, evidence_snapshot_hash=text_hash("evidence"),
        policy_hash=policy_hash(policy))


def _output(binding):
    return ResourceReviewInitialV1.model_validate({
        "binding": binding.model_dump(mode="json"),
        "dimensions": {"factual_evidence": "pass", "difficulty": "pass", "self_contained": "pass"},
        "targets": [{"target": "目标一", "status": "covered", "reason": "已讲解", "location": {"kind": "root"}}],
        "hallucination_score": 0.0, "issues": [], "omitted_blocking_issues": False,
    })


def _ledger(policy):
    material = _material()
    binding = _binding(material, policy)
    output = _output(binding)
    return append_model_observation_v1(
        previous=None, binding=binding, step_id="step-1", output=output, material=material,
        adapter=LectureAdapter(), parent_text=None, parent_comparison_hash=None,
        coverage_threshold=policy.coverage_threshold,
        max_consecutive_unchanged=policy.max_consecutive_unchanged)


def _v4(policy=None, *, ledger=None, run_id="run-1", step_id="step-1", repairs=()):
    policy = policy or _policy()
    ledger = ledger or _ledger(policy)
    summary = summarize_review_calls([])
    resource_audit = ReviewResourceAuditV1(
        resource_id="res-1", review_id="rev-1", resource_spec_id="spec-1", resource_type="讲义",
        structure_status="passed", semantic_status="passed", decision="approve")
    return ReviewAuditRecordV4(
        schema_version="4.0", run_id=run_id, step_id=step_id, generation_attempt=1, revision_count=0,
        policy=ReviewPolicySnapshotV1(), decision="approve", node_wall_ms=1, resources=[resource_audit],
        calls=[], summary=summary,
        resource_review_policy=policy, resource_review_policy_hash=policy_hash(policy),
        resource_ledgers=[ledger], repairs=list(repairs))


def test_v4_model_roundtrips_and_preserves_namespace():
    record = _v4()
    assert record.schema_version == "4.0"
    assert audit_record_model(record) is ReviewAuditRecordV4
    assert audit_record_model({"schema_version": "4.0"}) is ReviewAuditRecordV4
    assert audit_namespace({"schema_version": "4.0"}) == AUDIT_V4_NAMESPACE
    assert audit_namespace({"schema_version": "1.0"}) == AUDIT_NAMESPACE


def test_v4_envelope_roundtrip_and_1mib_bounded():
    record = _v4()
    envelope = review_audit_envelope(record, run_id="run-1", step_id="step-1")
    assert envelope["schema_version"] == "4.0"
    assert len(str(envelope).encode("utf-8")) < 1024 * 1024
    payload = {"review_audit_v4": envelope}
    assert select_audit_envelope(payload) == envelope


def test_v4_rejects_policy_hash_mismatch():
    record = _v4()
    data = record.model_dump(mode="json")
    data["resource_review_policy_hash"] = text_hash("tampered")
    with pytest.raises(ValueError):
        ReviewAuditRecordV4.model_validate(data)


def test_v4_rejects_ledger_ownership_mismatch():
    record = _v4()
    data = record.model_dump(mode="json")
    data["resource_ledgers"][0]["binding"]["resource_id"] = "other-res"
    with pytest.raises(ValueError):
        ReviewAuditRecordV4.model_validate(data)


def test_v4_approve_requires_verified_ledger():
    record = _v4(ledger=None)
    # Build without a ledger by dropping it from the payload.
    data = record.model_dump(mode="json")
    data["resource_ledgers"] = []
    with pytest.raises(ValueError) as exc:
        ReviewAuditRecordV4.model_validate(data)
    assert "verified ledger" in str(exc.value)


def test_v4_repair_final_hash_must_match_committed_result():
    from app.models.shared.persistence import canonical_hash
    policy = _policy()
    ledger = _ledger(policy)
    committed = ledger.observations[-1].output_hash
    first_output = {"binding": {}, "issues": []}
    repair = ReviewRepairRecordV3(
        review_id="rev-1", resource_id="res-1", first_call_id="c1", correction_call_id="c2",
        error_codes=["X"], error_paths=["findings"], first_output=first_output,
        first_output_hash=canonical_hash(first_output), attempted=True, first_attempts=1,
        correction_attempts=1, corrected=True, final_output_hash=committed)
    record = _v4(policy=policy, ledger=ledger, repairs=[repair])
    assert record.repairs[0].final_call_id == "c2"


def test_private_fields_excluded_from_public_payload():
    record = _v4()
    envelope = review_audit_envelope(record, run_id="run-1", step_id="step-1")
    public = public_review_payload({"review_audit_v4": envelope, "review": {"decision": "approve"}})
    assert "review_audit_v4" not in public
    assert "resource_review_policy" not in public
    assert public["review"] == {"decision": "approve"}
