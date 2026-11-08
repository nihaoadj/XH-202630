import pytest

from app.models.reviews.lecture_review import LectureReviewPolicyV1
from app.models.reviews.review_audit import (
    ReviewAuditRecordV2, ReviewPolicySnapshotV1, ReviewResourceAuditV1,
    review_audit_envelope, select_audit_envelope, summarize_review_calls,
)
from app.models.shared.persistence import canonical_hash
from tests.unit.agents.test_lecture_ledger import append
from tests.unit.agents.test_lecture_review_contract import make_output


def record():
    policy = LectureReviewPolicyV1(context_tokens=64000, max_output_tokens=12000)
    digest = canonical_hash(policy.model_dump(mode="json"))
    output = make_output()
    output = output.model_copy(update={"binding": output.binding.model_copy(update={"policy_hash": digest})})
    ledger = append(output)
    return ReviewAuditRecordV2(run_id="run", step_id="step1", generation_attempt=1,
        revision_count=0, policy=ReviewPolicySnapshotV1(), decision="approve", node_wall_ms=1,
        resources=[ReviewResourceAuditV1(resource_id="resource", review_id="review", resource_spec_id="spec",
            resource_type="讲义", structure_status="passed", semantic_status="passed", decision="approve")],
        calls=[], summary=summarize_review_calls([]), lecture_review_policy=policy,
        lecture_review_policy_hash=digest, lecture_ledgers=[ledger])


def test_v2_explicit_namespace_and_hash_and_ownership():
    audit = record()
    envelope = review_audit_envelope(audit, run_id="run", step_id="step1")
    assert envelope["schema_version"] == "2.0"
    assert select_audit_envelope({"review_audit_v2": envelope}) == envelope
    with pytest.raises(ValueError, match="multiple"):
        select_audit_envelope({"review_audit_v2": envelope, "review_audit_v1": envelope})
    with pytest.raises(ValueError, match="namespace"):
        select_audit_envelope({"review_audit_v1": envelope})
    with pytest.raises(ValueError, match="ownership"):
        review_audit_envelope(audit, run_id="other", step_id="step1")


def test_v2_rejects_policy_corruption_and_unknown_schema():
    data = record().model_dump(mode="json")
    data["lecture_review_policy_hash"] = "f" * 64
    with pytest.raises(ValueError, match="policy hash"):
        review_audit_envelope(data, run_id="run", step_id="step1")
    data["schema_version"] = "999.0"
    with pytest.raises(ValueError, match="unknown"):
        review_audit_envelope(data, run_id="run", step_id="step1")
