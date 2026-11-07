"""Private, bounded review evidence. Never use these models as HTTP responses."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.reviews.lecture_review import LectureLedgerV1, LectureReviewPolicyV1
from app.models.reviews.lecture_review_v2 import LectureLedgerV2, LectureReviewPolicyV2
from app.models.reviews.resource_review import ResourceLedgerV1
from app.models.reviews.resource_review_policy import RESOURCE_ADAPTER_TYPES, ResourceReviewPolicyV1

from app.models.shared.llm import LLMAttemptSummary, LLMUsage
from app.models.shared.persistence import canonical_hash


MAX_REVIEW_AUDIT_BYTES = 1024 * 1024
AUDIT_NAMESPACE = "review_audit_v1"
PRIVATE_REVIEW_FIELDS = frozenset({"specialized_reviews", "review_audit", "review_audit_v1", "review_policy",
                                   "review_audit_refs", "assessment_findings", "assessment_payload",
                                   "review_audit_v2", "review_audit_v3", "lecture_review_policy", "lecture_review_policy_hash",
                                   "lecture_review_contract_version", "lecture_ledgers", "lecture_revision",
                                   "lecture_stop_reasons", "lecture_dispatch_snapshot",
                                   "review_audit_v4", "resource_review_policy", "resource_review_policy_hash",
                                   "resource_review_contract_version", "resource_ledgers", "resource_revision",
                                   "resource_stop_reasons", "resource_dispatch_snapshot",
                                   "resource_review_identity", "resource_review_identity_hash"})
PROFILE_VERSIONS = {
    "content_v2": "2.0", "practice_semantic_v2": "2.0",
    "assessment_scope_v1": "1.0", "assessment_package_v1": "2.0",
    "assessment_combined_v2": "2.0", "empty_resource_compat_v1": "1.0",
}


def public_review_payload(review: dict) -> dict:
    """Keep historical summary keys while excluding private review namespaces."""
    return {key: value for key, value in review.items() if key not in PRIVATE_REVIEW_FIELDS}


class PrivateReviewModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())


class ReviewPolicySnapshotV1(PrivateReviewModel):
    schema_version: Literal["1.0"] = "1.0"
    audit_schema_version: Literal["1.0"] = "1.0"
    ruleset_version: Literal["resource-review-v2"] = "resource-review-v2"
    assessment_strategy: Literal["two_stage_v1", "combined_v2"] = "two_stage_v1"
    combined_context_tokens: int | None = Field(default=None, gt=0)
    combined_max_output_tokens: int = Field(default=16384, ge=256, le=65536)
    profile_versions: dict[str, str] = Field(default_factory=lambda: dict(PROFILE_VERSIONS))

    @model_validator(mode="after")
    def validate_policy(self):
        if self.assessment_strategy == "combined_v2" and self.combined_context_tokens is None:
            raise ValueError("combined review requires an explicit context window")
        if self.profile_versions != PROFILE_VERSIONS:
            raise ValueError("review profile versions do not match this ruleset")
        return self


class ReviewFindingV1(PrivateReviewModel):
    question_id: str = Field(min_length=1, max_length=128)
    skill_node_id: str = Field(min_length=1, max_length=128)
    codes: list[str] = Field(default_factory=list, max_length=4)
    scope_decision: Literal["in_scope", "out_of_scope", "insufficient_evidence"]
    supported_evidence_ids: list[str] = Field(default_factory=list, max_length=1)
    answer_check: Literal["pass", "fail", "insufficient_evidence"] | None = None
    clarity_check: Literal["pass", "fail"] | None = None
    rubric_check: Literal["pass", "fail", "insufficient_evidence", "not_applicable"] | None = None
    reason: str = Field(min_length=1, max_length=80)


class ReviewIssueLocationV1(PrivateReviewModel):
    code: str = Field(min_length=1, max_length=64)
    severity: Literal["low", "medium", "high", "critical"]
    knowledge_point: str | None = Field(default=None, max_length=128)
    question_ids: list[str] = Field(default_factory=list, max_length=300)
    step_ids: list[str] = Field(default_factory=list, max_length=12)


class ReviewResourceAuditV1(PrivateReviewModel):
    resource_id: str
    review_id: str
    resource_spec_id: str | None = None
    resource_type: str
    structure_status: Literal["passed", "failed", "not_checked"]
    semantic_status: Literal["passed", "failed", "unavailable", "not_run"]
    execution_status: Literal["not_run"] = "not_run"
    decision: Literal["approve", "revise", "reject", "human_review"]
    profiles: list[str] = Field(default_factory=list)
    prompt_fingerprints: list[str] = Field(default_factory=list)
    findings: list[ReviewFindingV1] = Field(default_factory=list, max_length=300)
    issue_locations: list[ReviewIssueLocationV1] = Field(default_factory=list, max_length=3)
    error_category: str | None = None


class ReviewCallRecordV1(PrivateReviewModel):
    call_id: str
    resource_id: str | None = None
    review_id: str | None = None
    phase: str
    profile_version: str
    prompt_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    fragment_versions: dict[str, str]
    gateway_role: str
    output_schema: str
    model_name: str | None = None
    status: Literal["started", "success", "error", "invalid_result"] = "started"
    error_code: str | None = None
    error_category: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    attempts: list[LLMAttemptSummary] = Field(default_factory=list, max_length=3)
    retry_count: int = Field(default=0, ge=0)
    usage: LLMUsage = Field(default_factory=LLMUsage)


class ReviewUsageSummaryV1(PrivateReviewModel):
    logical_call_count: int = Field(ge=0)
    gateway_attempt_count: int = Field(ge=0)
    retry_count: int = Field(ge=0)
    known_latency_ms: int = Field(ge=0)
    usage: LLMUsage
    known_usage: LLMUsage
    usage_complete: dict[str, bool]


def summarize_review_calls(calls: list[ReviewCallRecordV1]) -> ReviewUsageSummaryV1:
    # Gateway usage already includes attempts. Never add attempt usage again.
    known, total, complete = {}, {}, {}
    for field in LLMUsage.model_fields:
        values = [getattr(call.usage, field) for call in calls]
        known[field] = sum(value for value in values if value is not None)
        complete[field] = all(value is not None for value in values)
        total[field] = known[field] if complete[field] else None
    return ReviewUsageSummaryV1(
        logical_call_count=len(calls), gateway_attempt_count=sum(len(c.attempts) for c in calls),
        retry_count=sum(c.retry_count for c in calls), known_latency_ms=sum(c.latency_ms for c in calls),
        usage=LLMUsage(**total), known_usage=LLMUsage(**known), usage_complete=complete,
    )


class ReviewAuditRecordV1(PrivateReviewModel):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str
    step_id: str
    generation_attempt: int = Field(ge=1)
    revision_count: int = Field(ge=0)
    policy: ReviewPolicySnapshotV1
    decision: Literal["approve", "revise", "reject", "human_review"]
    node_wall_ms: int = Field(ge=0)
    resources: list[ReviewResourceAuditV1] = Field(default_factory=list, max_length=100)
    calls: list[ReviewCallRecordV1] = Field(default_factory=list, max_length=300)
    summary: ReviewUsageSummaryV1

    @model_validator(mode="after")
    def validate_totals(self):
        if len({c.call_id for c in self.calls}) != len(self.calls):
            raise ValueError("duplicate review logical call")
        if len({r.resource_id for r in self.resources}) != len(self.resources):
            raise ValueError("duplicate review resource")
        if self.summary != summarize_review_calls(self.calls):
            raise ValueError("review usage summary mismatch")
        by_id = {r.resource_id: r.review_id for r in self.resources}
        for call in self.calls:
            if call.resource_id is not None and by_id.get(call.resource_id) != call.review_id:
                raise ValueError("review call resource ownership mismatch")
            if call.status == "started":
                raise ValueError("review observation incomplete")
        return self


class ReviewAuditRecordV2(ReviewAuditRecordV1):
    schema_version: Literal["2.0"] = "2.0"
    lecture_review_policy: LectureReviewPolicyV1
    lecture_review_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lecture_ledgers: list[LectureLedgerV1] = Field(max_length=100)

    @model_validator(mode="after")
    def validate_lectures(self):
        expected = hashlib.sha256(_canonical(self.lecture_review_policy.model_dump(mode="json"))).hexdigest()
        if self.lecture_review_policy_hash != expected:
            raise ValueError("lecture audit policy hash mismatch")
        resources = {item.resource_id: item for item in self.resources}
        seen = set()
        for ledger in self.lecture_ledgers:
            binding = ledger.binding
            if (binding.run_id != self.run_id or binding.policy_hash != expected or
                    binding.resource_id not in resources or binding.resource_id in seen):
                raise ValueError("lecture audit ledger ownership mismatch")
            if resources[binding.resource_id].resource_spec_id != binding.resource_spec_id:
                raise ValueError("lecture audit resource specification mismatch")
            if ledger.observations[-1].step_id != self.step_id:
                raise ValueError("lecture audit observation step mismatch")
            if resources[binding.resource_id].decision == "approve" and ledger.observations[-1].decision != "approve":
                raise ValueError("lecture audit cannot approve an open ledger")
            seen.add(binding.resource_id)
        for resource in self.resources:
            if resource.resource_type == "讲义" and resource.decision == "approve" and resource.resource_id not in seen:
                raise ValueError("approved lecture requires a verified ledger")
        return self


class ReviewRepairRecordV3(PrivateReviewModel):
    """Bounded repair diagnostics for one lecture review round.

    ``first_output`` is the invalid first result kept as a controlled attachment;
    it is bounded by the envelope limit and never written to public traces.
    """

    review_id: str
    resource_id: str
    first_call_id: str
    correction_call_id: str | None = None
    error_codes: list[str] = Field(min_length=1, max_length=8)
    error_paths: list[str] = Field(default_factory=list, max_length=8)
    first_output: dict | None = None
    first_output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempted: bool
    first_attempts: int = Field(ge=0, le=3)
    correction_attempts: int = Field(ge=0, le=3)
    corrected: bool
    stop_reason: str | None = None
    final_output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def validate_repair(self):
        if self.first_output is not None and canonical_hash(self.first_output) != self.first_output_hash:
            raise ValueError("lecture repair attachment hash mismatch")
        if self.corrected and self.final_output_hash is None:
            raise ValueError("corrected lecture repair requires the final output hash")
        if self.corrected and self.correction_call_id is None:
            raise ValueError("corrected lecture repair requires the correction call")
        return self

    @property
    def final_call_id(self) -> str:
        """The call whose output is the final result of this round.

        Derived from the already-persisted first/correction identities, never
        stored separately: a corrected round's final result came from the
        correction call; an uncorrected or un-attempted round's final result is
        still the first call (the correction never produced a legal output).
        This keeps the persisted V3 payload/hash unchanged for already-sealed
        records.
        """
        if self.corrected and self.correction_call_id is not None:
            return self.correction_call_id
        return self.first_call_id


class ReviewAuditRecordV3(ReviewAuditRecordV1):
    schema_version: Literal["3.0"] = "3.0"
    lecture_review_policy: LectureReviewPolicyV1 | LectureReviewPolicyV2
    lecture_review_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    lecture_ledgers: list[LectureLedgerV1 | LectureLedgerV2] = Field(max_length=100)
    repairs: list[ReviewRepairRecordV3] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_lectures(self):
        expected = hashlib.sha256(_canonical(self.lecture_review_policy.model_dump(mode="json"))).hexdigest()
        if self.lecture_review_policy_hash != expected:
            raise ValueError("lecture audit policy hash mismatch")
        resources = {item.resource_id: item for item in self.resources}
        seen = set()
        hashes = {}
        for ledger in self.lecture_ledgers:
            binding = ledger.binding
            if (binding.run_id != self.run_id or binding.policy_hash != expected or
                    binding.resource_id not in resources or binding.resource_id in seen):
                raise ValueError("lecture audit ledger ownership mismatch")
            if resources[binding.resource_id].resource_spec_id != binding.resource_spec_id:
                raise ValueError("lecture audit resource specification mismatch")
            if ledger.observations[-1].step_id != self.step_id:
                raise ValueError("lecture audit observation step mismatch")
            if resources[binding.resource_id].decision == "approve" and ledger.observations[-1].decision != "approve":
                raise ValueError("lecture audit cannot approve an open ledger")
            seen.add(binding.resource_id)
            hashes[binding.resource_id] = ledger.observations[-1].output_hash
        for resource in self.resources:
            if resource.resource_type == "讲义" and resource.decision == "approve" and resource.resource_id not in seen:
                raise ValueError("approved lecture requires a verified ledger")
        for repair in self.repairs:
            if repair.resource_id not in resources:
                raise ValueError("lecture repair names an unknown resource")
            if repair.corrected and hashes.get(repair.resource_id) != repair.final_output_hash:
                raise ValueError("lecture repair final hash is not the committed result")
        return self


class ReviewAuditRecordV4(ReviewAuditRecordV1):
    """Generic resource-issue audit for the ``resource_issue_v1`` strategy.

    Persists the frozen generic policy/hash, one generic ledger per reviewed
    resource, and the bounded first-result correction attachments.  The repair
    record reuses the V3 bounded-repair shape (identical fields) without
    changing its serialization or the V1-V3 historical hashes.
    """

    schema_version: Literal["4.0"] = "4.0"
    resource_review_policy: ResourceReviewPolicyV1
    resource_review_policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    resource_ledgers: list[ResourceLedgerV1] = Field(max_length=100)
    repairs: list[ReviewRepairRecordV3] = Field(default_factory=list, max_length=24)

    @model_validator(mode="after")
    def validate_resources(self):
        expected = hashlib.sha256(_canonical(self.resource_review_policy.model_dump(mode="json"))).hexdigest()
        if self.resource_review_policy_hash != expected:
            raise ValueError("resource audit policy hash mismatch")
        resources = {item.resource_id: item for item in self.resources}
        seen = set()
        hashes = {}
        for ledger in self.resource_ledgers:
            binding = ledger.binding
            if (binding.run_id != self.run_id or binding.policy_hash != expected or
                    binding.resource_id not in resources or binding.resource_id in seen):
                raise ValueError("resource audit ledger ownership mismatch")
            if resources[binding.resource_id].resource_spec_id != binding.resource_spec_id:
                raise ValueError("resource audit resource specification mismatch")
            if ledger.observations[-1].step_id != self.step_id:
                raise ValueError("resource audit observation step mismatch")
            if resources[binding.resource_id].decision == "approve" and ledger.observations[-1].decision != "approve":
                raise ValueError("resource audit cannot approve an open ledger")
            seen.add(binding.resource_id)
            hashes[binding.resource_id] = ledger.observations[-1].output_hash
        for resource in self.resources:
            if resource.resource_type in RESOURCE_ADAPTER_TYPES and resource.decision == "approve" and resource.resource_id not in seen:
                raise ValueError("approved resource requires a verified ledger")
        for repair in self.repairs:
            if repair.resource_id not in resources:
                raise ValueError("resource repair names an unknown resource")
            if repair.corrected and hashes.get(repair.resource_id) != repair.final_output_hash:
                raise ValueError("resource repair final hash is not the committed result")
        return self


def audit_record_model(value):
    version = value.schema_version if isinstance(value, PrivateReviewModel) else value.get("schema_version")
    if version == "1.0":
        return ReviewAuditRecordV1
    if version == "2.0":
        return ReviewAuditRecordV2
    if version == "3.0":
        return ReviewAuditRecordV3
    if version == "4.0":
        return ReviewAuditRecordV4
    raise ValueError("unknown review audit schema version")


AUDIT_V3_NAMESPACE = "review_audit_v3"
AUDIT_V4_NAMESPACE = "review_audit_v4"


def audit_namespace(envelope):
    return {"2.0": "review_audit_v2", "3.0": AUDIT_V3_NAMESPACE,
            "4.0": AUDIT_V4_NAMESPACE}.get(envelope["schema_version"], AUDIT_NAMESPACE)


def select_audit_envelope(payload):
    keys = [key for key in (AUDIT_NAMESPACE, "review_audit_v2", AUDIT_V3_NAMESPACE, AUDIT_V4_NAMESPACE) if key in payload]
    if len(keys) > 1:
        raise ValueError("multiple review audit namespaces")
    if not keys:
        return None
    envelope = payload[keys[0]]
    if envelope is None or audit_namespace(envelope) != keys[0]:
        raise ValueError("review audit namespace mismatch")
    return envelope


def _canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def review_audit_envelope(audit: ReviewAuditRecordV1 | dict, *, run_id: str, step_id: str) -> dict:
    record = audit_record_model(audit).model_validate(audit)
    if record.run_id != run_id or record.step_id != step_id:
        raise ValueError("review audit run/step ownership mismatch")
    payload = record.model_dump(mode="json")
    envelope = {"schema_version": record.schema_version, "audit_hash": hashlib.sha256(_canonical(payload)).hexdigest(), "payload": payload}
    if len(_canonical(envelope)) > MAX_REVIEW_AUDIT_BYTES:
        raise ValueError("review audit exceeds maximum size")
    return envelope


def step_review_audit_envelope(*, audit, run_id, step_id, node_name, generation_attempt, trace, request_snapshot):
    if audit is None:
        return None
    envelope = review_audit_envelope(audit, run_id=run_id, step_id=step_id)
    payload = envelope["payload"]
    if request_snapshot.get("lecture_review_contract_version") is not None and envelope["schema_version"] not in {"2.0", "3.0"}:
        raise ValueError("new lecture strategy requires a versioned audit")
    if request_snapshot.get("lecture_review_contract_version") == "2.0" and envelope["schema_version"] != "3.0":
        raise ValueError("lecture contract 2.0 requires the V3 audit")
    if request_snapshot.get("resource_review_contract_version") is not None and envelope["schema_version"] != "4.0":
        raise ValueError("new resource strategy requires the V4 audit")
    if envelope["schema_version"] in {"2.0", "3.0"}:
        for key in ("lecture_review_policy", "lecture_review_policy_hash"):
            if payload[key] != request_snapshot.get(key):
                raise ValueError("lecture audit frozen policy mismatch")
    if envelope["schema_version"] == "4.0":
        for key in ("resource_review_policy", "resource_review_policy_hash"):
            if payload[key] != request_snapshot.get(key):
                raise ValueError("resource audit frozen policy mismatch")
    frozen = request_snapshot.get("review_policy")
    if frozen is not None and payload["policy"] != ReviewPolicySnapshotV1.model_validate(frozen).model_dump(mode="json"):
        raise ValueError("review audit frozen policy mismatch")
    if node_name not in {"review", "reviewer"} or payload["generation_attempt"] != generation_attempt:
        raise ValueError("review audit step ownership mismatch")
    if set(trace.get("resource_ids") or []) != {r["resource_id"] for r in payload["resources"]}:
        raise ValueError("review audit resource ownership mismatch")
    if set(trace.get("review_ids") or []) != {r["review_id"] for r in payload["resources"]}:
        raise ValueError("review audit review ownership mismatch")
    return envelope


def read_review_audit(*, envelope: dict | None, run_id: str, step_id: str, node_name: str,
                      status: str, request_snapshot: dict, checkpoints: list) -> ReviewAuditRecordV1 | None:
    expected = ((request_snapshot.get("review_policy") or {}).get("audit_schema_version") == "1.0"
                or request_snapshot.get("lecture_review_contract_version") is not None
                or request_snapshot.get("resource_review_contract_version") is not None)
    if envelope is None:
        if expected and node_name in {"review", "reviewer"}:
            if status in {"success", "degraded", "human_review"}:
                raise ValueError("completed review audit missing")
            raise ValueError("review observation incomplete")
        return None  # Legacy, unrecorded. Never synthesize usage or approval.
    if set(envelope) != {"schema_version", "audit_hash", "payload"}:
        raise ValueError("review audit envelope invalid")
    checked = review_audit_envelope(envelope["payload"], run_id=run_id, step_id=step_id)
    if checked != envelope:
        raise ValueError("review audit hash mismatch")
    if request_snapshot.get("lecture_review_contract_version") is not None and checked["schema_version"] not in {"2.0", "3.0"}:
        raise ValueError("new lecture strategy requires a versioned audit")
    if request_snapshot.get("lecture_review_contract_version") == "2.0" and checked["schema_version"] != "3.0":
        raise ValueError("lecture contract 2.0 requires the V3 audit")
    if request_snapshot.get("resource_review_contract_version") is not None and checked["schema_version"] != "4.0":
        raise ValueError("new resource strategy requires the V4 audit")
    if checked["schema_version"] in {"2.0", "3.0"}:
        for key in ("lecture_review_policy", "lecture_review_policy_hash"):
            if checked["payload"][key] != request_snapshot.get(key):
                raise ValueError("lecture audit frozen policy mismatch")
    if checked["schema_version"] == "4.0":
        for key in ("resource_review_policy", "resource_review_policy_hash"):
            if checked["payload"][key] != request_snapshot.get(key):
                raise ValueError("resource audit frozen policy mismatch")
    frozen = request_snapshot.get("review_policy")
    if frozen is not None and checked["payload"]["policy"] != ReviewPolicySnapshotV1.model_validate(frozen).model_dump(mode="json"):
        raise ValueError("review audit frozen policy mismatch")
    for checkpoint in checkpoints:
        if checkpoint.step_id != step_id:
            continue
        refs = checkpoint.state_projection.get("review_audit_refs", [])
        matching = [r for r in refs if r.get("step_id") == step_id]
        review_ids = [r["review_id"] for r in checked["payload"]["resources"]]
        if len(matching) != 1 or matching[0].get("audit_hash") != checked["audit_hash"] or matching[0].get("review_ids") != review_ids:
            raise ValueError("review checkpoint audit reference invalid")
        if checked["schema_version"] in {"2.0", "3.0"}:
            if matching[0].get("schema_version") != checked["schema_version"]:
                raise ValueError("lecture checkpoint audit version mismatch")
            for key in ("lecture_review_policy", "lecture_review_policy_hash"):
                if checkpoint.state_projection.get(key) != request_snapshot.get(key):
                    raise ValueError("lecture checkpoint frozen policy mismatch")
        if checked["schema_version"] == "4.0":
            if matching[0].get("schema_version") != checked["schema_version"]:
                raise ValueError("resource checkpoint audit version mismatch")
            for key in ("resource_review_policy", "resource_review_policy_hash"):
                if checkpoint.state_projection.get(key) != request_snapshot.get(key):
                    raise ValueError("resource checkpoint frozen policy mismatch")
    return audit_record_model(checked["payload"]).model_validate(checked["payload"])
