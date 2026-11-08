"""Private, bounded v1 contracts. Never include these records in public DTOs."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator
from app.models.courseware.content import (
    CoursewarePlanEnrichmentV2, CoursewareObjectiveEnrichment, CoursewareSceneEnrichment,
    PracticeGuideCoverEnrichment, ReviewPracticeCoursewarePlanEnrichment, ReviewPracticeNodeSummary,
)

Identifier = Annotated[str, Field(min_length=1, max_length=256, pattern=r"^\S(?:.*\S)?$")]
Digest = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
RuleId = Literal["factual_support", "scope_alignment", "learning_guidance", "procedural_consistency", "code_constraints"]
ReviewStatus = Literal["pending", "approved", "needs_revision", "unavailable", "degraded", "blocked", "not_applicable"]
MAX_SPEC_BYTES = 2 * 1024 * 1024


class StrictObjectiveCandidate(CoursewareObjectiveEnrichment):
    model_config = ConfigDict(extra="forbid")


class StrictSceneCandidate(CoursewareSceneEnrichment):
    model_config = ConfigDict(extra="forbid")


class StrictCoverCandidate(PracticeGuideCoverEnrichment):
    model_config = ConfigDict(extra="forbid")


class StrictNodeSummaryCandidate(ReviewPracticeNodeSummary):
    model_config = ConfigDict(extra="forbid")


class CoursewarePlanEnrichmentCandidateV1(CoursewarePlanEnrichmentV2):
    """Same generation fields/bounds; only the new strategy closes extras."""
    model_config = ConfigDict(extra="forbid")
    objectives: list[StrictObjectiveCandidate] = Field(default_factory=list, max_length=8)
    scenes: list[StrictSceneCandidate] = Field(default_factory=list, max_length=24)
    practice_cover: StrictCoverCandidate | None = None


class ReviewPracticeEnrichmentCandidateV1(ReviewPracticeCoursewarePlanEnrichment):
    model_config = ConfigDict(extra="forbid")
    node_summaries: list[StrictNodeSummaryCandidate] = Field(default_factory=list, max_length=3)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def json_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class PrivateContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, protected_namespaces=())
    schema_version: Literal["1.0"] = "1.0"


class FrozenBudgetV1(PrivateContract):
    total_tokens: int = Field(gt=0)
    stage_tokens: dict[Literal["planner", "scene", "quality_review", "revision"], int]
    stage_seconds: dict[Literal["planner", "scene", "quality_review", "revision"], float]
    quality_reserve: int = Field(ge=0)
    revision_reserve: int = Field(ge=0)
    call_seconds: float = Field(gt=0)
    deadline: str = Field(max_length=64)

    @model_validator(mode="after")
    def complete(self):
        stages = {"planner", "scene", "quality_review", "revision"}
        if set(self.stage_tokens) != stages or set(self.stage_seconds) != stages:
            raise ValueError("incomplete frozen budget")
        if any(v < 0 for v in self.stage_tokens.values()) or any(v < 0 for v in self.stage_seconds.values()):
            raise ValueError("negative stage budget")
        if sum(self.stage_tokens.values()) > self.total_tokens:
            raise ValueError("stage budgets exceed total")
        return self


class ContentReviewPolicyV1(PrivateContract):
    mode: Literal["legacy_v1", "content_v1"] = "content_v1"
    ruleset_version: Literal["courseware-content-rules-v1"] = "courseware-content-rules-v1"
    registry_version: Literal["courseware-adapters-v1"] = "courseware-adapters-v1"
    projection_version: Literal["courseware-projection-v1"] = "courseware-projection-v1"
    context_tokens: int = Field(ge=16384)
    max_output_tokens: Literal[8192] = 8192
    max_batches: Literal[8] = 8
    max_revision_rounds: int = Field(default=1, ge=0, le=1)
    release_policy: Literal["strict", "resilient"]
    model_fingerprint: Digest
    estimator_id: Identifier
    budget: FrozenBudgetV1


class ContentReviewBindingV1(PrivateContract):
    mode: Literal["content_v1"] = "content_v1"
    spec_id: Annotated[str, Field(min_length=1, max_length=96)]
    policy_hash: Digest


class FieldLocatorV1(PrivateContract):
    space: Literal["source", "candidate", "document", "spec", "template"]
    owner_id: Identifier
    tokens: list[Annotated[str, Field(min_length=1, max_length=256)] | Annotated[int, Field(ge=0, le=4096)]] = Field(max_length=16)


class ContentItemV1(PrivateContract):
    item_id: Identifier
    owner_id: Identifier
    origin: Literal["source", "ai", "template", "derived", "user", "unused"]
    source: FieldLocatorV1
    targets: list[FieldLocatorV1] = Field(default_factory=list, max_length=128)
    value_hash: Digest
    rule_ids: list[RuleId] = Field(default_factory=list, max_length=6)
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=64)
    dependency_ids: list[Identifier] = Field(default_factory=list, max_length=128)


class ContentInventoryV1(PrivateContract):
    run_id: Identifier
    source_id: Identifier
    source_schema: Annotated[str, Field(max_length=32)]
    adapter_version: Annotated[str, Field(max_length=48)]
    items: list[ContentItemV1] = Field(max_length=4096)

    @model_validator(mode="after")
    def unique(self):
        if len({i.item_id for i in self.items}) != len(self.items):
            raise ValueError("duplicate inventory item")
        return self


class ReviewItemV1(ContentItemV1):
    value: Annotated[str, Field(max_length=8192)]
    max_chars: int = Field(gt=0, le=8192)


class EvidenceV1(PrivateContract):
    evidence_id: Identifier
    kind: Literal["source_content", "source_answer", "course_rule"]
    text: Annotated[str, Field(min_length=1, max_length=32768)]
    source: FieldLocatorV1
    value_hash: Digest

    @model_validator(mode="after")
    def verify_hash(self):
        if json_hash(self.text) != self.value_hash:
            raise ValueError("evidence hash mismatch")
        return self


class EvidenceBundleV1(PrivateContract):
    items: list[EvidenceV1] = Field(max_length=512)

    @model_validator(mode="after")
    def unique(self):
        if len({i.evidence_id for i in self.items}) != len(self.items):
            raise ValueError("duplicate evidence")
        return self


class FieldIssueV1(PrivateContract):
    code: Literal["factual_conflict", "evidence_gap", "scope_exaggeration", "misleading_guidance", "procedure_conflict", "code_constraint"]
    severity: Literal["warning", "error"]
    reason: Annotated[str, Field(min_length=1, max_length=160)]


class RuleResultV1(PrivateContract):
    rule_id: RuleId
    verdict: Literal["pass", "fail", "insufficient_evidence"]
    evidence_ids: list[Identifier] = Field(default_factory=list, max_length=4)
    problems: list[FieldIssueV1] = Field(default_factory=list, max_length=1)
    factual_support: Literal["supported", "contradicted", "insufficient_evidence", "not_applicable"] | None = None
    reason: Annotated[str, Field(max_length=160)] = ""


class FieldReviewResultV1(PrivateContract):
    item_id: Identifier
    value_hash: Digest
    rules: list[RuleResultV1] = Field(min_length=1, max_length=6)


class BatchResultV1(PrivateContract):
    batch_id: Annotated[str, Field(min_length=1, max_length=96)]
    identity: Digest
    value_hash: Digest
    results: list[FieldReviewResultV1] = Field(max_length=128)


class RevisionChangeV1(PrivateContract):
    item_id: Identifier
    old_value_hash: Digest
    new_value: Annotated[str, Field(min_length=1, max_length=8192)]


class RevisionPatchV1(PrivateContract):
    identity: Digest
    changes: list[RevisionChangeV1] = Field(max_length=128)


class ContentReviewRecordV1(PrivateContract):
    identity: Digest
    source_hash: Digest
    design_hash: Digest
    inventory_hash: Digest
    evidence_hash: Digest
    value_hash: Digest
    adapter_version: Annotated[str, Field(max_length=48)]
    prompt_fingerprint: Digest
    fragment_versions: dict[Annotated[str, Field(max_length=48)], Annotated[str, Field(max_length=48)]] = Field(max_length=16)
    model_fingerprint: Digest
    status: ReviewStatus
    reason: Annotated[str, Field(max_length=160)] = ""
    original_values: dict[str, Any]
    approved_values: dict[str, Any]
    candidate_schema: Annotated[str, Field(max_length=96)]
    template_version: Literal["courseware-templates-v1"] = "courseware-templates-v1"
    revision_rounds: int = Field(default=0, ge=0, le=1)
    batches: list[BatchResultV1] = Field(default_factory=list, max_length=24)
    results: list[FieldReviewResultV1] = Field(default_factory=list, max_length=128)
    manifest: list[ContentItemV1] = Field(default_factory=list, max_length=4096)
    document_hash: Digest | None = None


class CallTicketV1(PrivateContract):
    ticket_id: Annotated[str, Field(max_length=96)]
    stage: Literal["planner", "scene", "quality_review", "revision"]
    phase: Annotated[str, Field(min_length=1, max_length=48)]
    status: Literal["reserved", "completed", "unknown"]
    input_reserved: int = Field(ge=0)
    output_reserved: int = Field(ge=1)
    attempts_reserved: int = Field(ge=1, le=3)
    charged_tokens: int = Field(ge=0)
    actual_input: int | None = Field(default=None, ge=0)
    actual_output: int | None = Field(default=None, ge=0)
    attempts: int | None = Field(default=None, ge=1, le=3)
    call_id: Annotated[str, Field(max_length=128)] | None = None
    duration_ms: int = Field(default=0, ge=0)
    error_code: Annotated[str, Field(max_length=64)] | None = None
    input_hash: Digest
    started_at: Annotated[str, Field(max_length=64)]
    prev_record_hash: Digest
    record_hash: Digest


class ContentReviewStateV1(PrivateContract):
    policy: ContentReviewPolicyV1
    phase: Literal["policy_only", "candidate", "reviewed"] = "policy_only"
    candidate: dict[str, Any] | None = None
    record: ContentReviewRecordV1 | None = None
    ledger: list[CallTicketV1] = Field(default_factory=list, max_length=256)
    execution_owner: Annotated[str, Field(max_length=96)] | None = None
    lease_until: Annotated[str, Field(max_length=64)] | None = None


class ContentReviewConflict(ValueError):
    code = "COURSEWARE_CONTENT_REVIEW_CONFLICT"


class ContentReviewBlocked(ValueError):
    code = "COURSEWARE_CONTENT_REVIEW_BLOCKED"


class ContentReviewBusy(RuntimeError):
    """A live owner remains authoritative; this is not a content rejection."""


def validate_private_spec(spec: dict, previous: dict | None = None) -> ContentReviewStateV1:
    if len(canonical_json(spec).encode("utf-8")) > MAX_SPEC_BYTES:
        raise ContentReviewBlocked("private spec size limit")
    state = ContentReviewStateV1.model_validate_json(canonical_json(spec["content_review"]))
    if previous is not None:
        prior = ContentReviewStateV1.model_validate(previous["content_review"])
        if prior.policy != state.policy:
            raise ContentReviewBlocked("frozen policy changed")
        if prior.record is not None and state.record is None:
            raise ContentReviewBlocked("approval removed")
        if prior.candidate is not None and prior.candidate != state.candidate:
            raise ContentReviewBlocked("original candidate changed")
        ranks = {"policy_only": 0, "candidate": 1, "reviewed": 2}
        if ranks[state.phase] < ranks[prior.phase]:
            raise ContentReviewBlocked("private phase regressed")
        controlled = {"content_review", "title", "enrichment", "review_practice_enrichment", "scenes"}
        if any(previous[k] != spec.get(k) for k in previous.keys() - controlled):
            raise ContentReviewBlocked("frozen design/namespace changed")
        if len(state.ledger) < len(prior.ledger):
            raise ContentReviewBlocked("ledger truncated")
        for old, new in zip(prior.ledger, state.ledger):
            if old != new:
                raise ContentReviewBlocked("ledger rewrite")
    prev = "0" * 64
    tickets = {}
    for ticket in state.ledger:
        raw = ticket.model_dump(mode="json", exclude={"record_hash"})
        if ticket.prev_record_hash != prev or ticket.record_hash != json_hash(raw):
            raise ContentReviewBlocked("ledger chain invalid")
        prev = ticket.record_hash
        old = tickets.get(ticket.ticket_id)
        if old is None and ticket.status != "reserved":
            raise ContentReviewBlocked("unreserved call")
        if old is not None:
            if old.status != "reserved" or ticket.status == "reserved":
                raise ContentReviewBlocked("non-monotonic ticket")
            for key in ("stage", "phase", "input_reserved", "output_reserved", "attempts_reserved", "input_hash", "started_at"):
                if getattr(old, key) != getattr(ticket, key):
                    raise ContentReviewBlocked("ticket reservation changed")
        tickets[ticket.ticket_id] = ticket
    return state


def binding_for_spec(row):
    state = validate_private_spec(row["spec_json"])
    if row["spec_id"] != f"cws_{row['run_id']}" or row["content_hash"] != json_hash(row["spec_json"]):
        raise ContentReviewBlocked("invalid initial spec identity/hash")
    return ContentReviewBindingV1(spec_id=row["spec_id"], policy_hash=json_hash(state.policy.model_dump(mode="json"))).model_dump(mode="json")
