"""Versioned generic contract for ordinary text-document review (T44).

This is the one shared closed loop for the six public/private text resources
(讲义 / 实操指南 / 分阶测试题 / 案例分析 / 复习清单 / 个性化纠错训练包).
It is a generalization of the lecture issue contract, not a copy: locations,
evidence, findings, program-gate observations and cross-version resolutions are
typed here and never reinterpreted through the lecture models.

Two observation origins exist.  ``program_gate`` observations are produced only
by the deterministic structure gates and never by a model; ``model_review``
observations are produced only by the semantic model.  A program-gate round
makes zero semantic calls and must never fabricate model risk or dimension
verdicts.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from .evidence_context import EvidenceContextCarryOverV1


class ResourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


SEMANTIC_DIMENSIONS = ("factual_evidence", "difficulty", "self_contained")
ALL_ISSUE_DIMENSIONS = ("factual_evidence", "coverage", "difficulty", "self_contained")
ISSUE_PATHS = (
    "add_from_evidence", "reorganize_existing", "remove_or_narrow", "synthetic_example",
    "replace_or_drop_exercise", "evidence_insufficient",
)
UNIT_CHANGES = ("retained", "revised", "replaced", "removed")


class ResourceEvidenceRefV1(ResourceContract):
    evidence_id: str = Field(min_length=1)
    excerpt_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class ResourceLocationV1(ResourceContract):
    """Server-index location.  Models may only cite ids/paths already present in
    the adapter's location index; arbitrary JSONPath/expressions are rejected."""

    kind: Literal["paragraph", "structured", "root"] = "root"
    locator_version: Literal["resource-locator-v1"] = "resource-locator-v1"
    # paragraph locations (讲义/案例分析/纠错包)
    paragraph_id: str | None = None
    heading_path: list[str] = Field(default_factory=list, max_length=12)
    quote: str | None = Field(default=None, min_length=1, max_length=240)
    # structured locations (实操指南/分阶测试题/复习清单)
    unit_id: str | None = Field(default=None, max_length=128)
    field_path: list[str] = Field(default_factory=list, max_length=12)
    missing_fields: list[str] = Field(default_factory=list, max_length=12)

    @model_validator(mode="after")
    def location_shape(self) -> "ResourceLocationV1":
        if self.kind == "paragraph":
            if self.paragraph_id is None:
                raise ValueError("paragraph location requires paragraph_id")
            if self.unit_id is not None or self.field_path or self.missing_fields:
                raise ValueError("paragraph location cannot carry structured fields")
        elif self.kind == "structured":
            if self.unit_id is None and not self.missing_fields:
                raise ValueError("structured location requires unit_id or missing_fields")
            if self.paragraph_id is not None or self.heading_path or self.quote is not None:
                raise ValueError("structured location cannot carry paragraph fields")
        elif self.kind == "root":
            if any((self.paragraph_id, self.unit_id, self.heading_path, self.field_path,
                    self.missing_fields, self.quote)):
                raise ValueError("root location must be empty")
        return self


class ResourceFindingV1(ResourceContract):
    """One per-question professional check result (assessment combined).

    Mirrors the existing combined assessment review: one finding per question
    carrying the scope/answer/clarity/rubric verdicts.  The server derives one
    version-bound ``finding_key`` per failed check; the model's issues must
    reference exactly the derived key set.
    """

    question_id: str = Field(min_length=1, max_length=128)
    skill_node_id: str = Field(default="", max_length=128)
    scope_decision: Literal["in_scope", "out_of_scope", "insufficient_evidence"]
    supported_evidence_ids: list[str] = Field(default_factory=list, max_length=1)
    answer_check: Literal["pass", "fail", "insufficient_evidence"] | None = None
    clarity_check: Literal["pass", "fail"] | None = None
    rubric_check: Literal["pass", "fail", "insufficient_evidence", "not_applicable"] | None = None
    reason: str = Field(min_length=1, max_length=200)


class ResourceIssueV1(ResourceContract):
    # Temporary in model output; replaced by the server's stable id on append.
    issue_id: str = Field(min_length=1)
    origin: Literal["program_gate", "model_review"] = "model_review"
    code: str = Field(min_length=1, max_length=64)
    severity: Literal["low", "medium", "high", "critical"]
    blocking: bool
    blocking_rule: str | None = None
    dimension: Literal["factual_evidence", "coverage", "difficulty", "self_contained"]
    affected_target_ids: list[str] = Field(default_factory=list, max_length=12)
    location: ResourceLocationV1
    impact: str = Field(min_length=1, max_length=500)
    requirement: str = Field(min_length=1, max_length=1000)
    acceptance: str = Field(min_length=1, max_length=1000)
    criteria_version: int = Field(ge=1)
    path: Literal["add_from_evidence", "reorganize_existing", "remove_or_narrow", "synthetic_example",
                  "replace_or_drop_exercise", "evidence_insufficient"]
    evidence_refs: list[ResourceEvidenceRefV1] = Field(default_factory=list, max_length=24)
    teaching_rule_id: str | None = None
    executability: Literal["executable", "evidence_insufficient"]
    rationale: str = Field(min_length=1, max_length=1000)
    # Assessment-only: version-bound keys of the failed per-question checks this
    # logical issue owns.  Empty for whole-package / program-gate issues.
    finding_keys: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def valid_issue(self) -> "ResourceIssueV1":
        if self.severity in {"high", "critical"} and not self.blocking:
            raise ValueError("high severity issue must block")
        if self.blocking and not self.blocking_rule:
            raise ValueError("blocking issue requires a blocking rule")
        if self.origin == "program_gate":
            # Program-gate issues are produced only by the deterministic gates:
            # no evidence, teaching rule or finding keys; the requirement is the
            # fixed reconstruction condition and the acceptance is the gate
            # re-passing on the same rule version.
            if self.evidence_refs or self.teaching_rule_id or self.finding_keys:
                raise ValueError("program gate issue cannot cite evidence or findings")
            if self.executability != "executable" or self.path != "reorganize_existing":
                raise ValueError("program gate issue has a fixed reconstruction path")
        else:
            if not self.evidence_refs and not self.teaching_rule_id and not self.finding_keys:
                raise ValueError("issue requires evidence, a teaching rule, or finding keys")
            if self.path in {"add_from_evidence", "synthetic_example"} and not self.evidence_refs:
                raise ValueError("technical addition requires frozen evidence")
            if (self.path == "evidence_insufficient") != (self.executability == "evidence_insufficient"):
                raise ValueError("path and executability disagree")
        if len(set(self.affected_target_ids)) != len(self.affected_target_ids):
            raise ValueError("duplicate affected target")
        if self.dimension == "coverage":
            if self.blocking and not self.affected_target_ids:
                raise ValueError("blocking coverage issue requires affected targets")
        elif self.affected_target_ids:
            raise ValueError("only coverage issues may affect specific targets")
        return self


class ResourceResolutionV1(ResourceContract):
    """Resolve the latest open observation against its bound parent version."""

    issue_id: str = Field(min_length=1)
    result: Literal["fixed", "still_open", "false_positive", "unverifiable"]
    reason: str = Field(min_length=1, max_length=1000)
    current_location: ResourceLocationV1 | None = None
    previous_location: ResourceLocationV1 | None = None
    evidence_refs: list[ResourceEvidenceRefV1] = Field(default_factory=list, max_length=24)
    unit_change: Literal["retained", "revised", "replaced", "removed"] = "retained"
    current_check_refs: list[str] = Field(default_factory=list, max_length=300)

    @model_validator(mode="after")
    def valid_resolution(self) -> "ResourceResolutionV1":
        if self.result in {"fixed", "still_open"} and self.current_location is None:
            raise ValueError("resolution requires current location")
        if self.result == "false_positive" and self.previous_location is None:
            raise ValueError("false positive requires previous location")
        if self.unit_change == "removed" and self.result == "fixed":
            # removed is allowed for fixed only when the original scope/target
            # gates still pass; the caller decides.  Do not forbid here.
            pass
        return self


class ResourceReopenV1(ResourceContract):
    issue_id: str = Field(min_length=1)
    current_location: ResourceLocationV1
    reason: str = Field(min_length=1, max_length=1000)
    current_check_refs: list[str] = Field(default_factory=list, max_length=300)
    evidence_refs: list[ResourceEvidenceRefV1] = Field(default_factory=list, max_length=24)


    @model_serializer(mode="wrap")
    def serialize_compatible(self, handler):
        data = handler(self)
        if "current_check_refs" not in self.model_fields_set:
            data.pop("current_check_refs", None)
        return data


class ResourceDimensionsV1(ResourceContract):
    factual_evidence: Literal["pass", "fail", "insufficient"]
    difficulty: Literal["pass", "fail", "insufficient"]
    self_contained: Literal["pass", "fail", "insufficient"]


class ResourceTargetCoverageV1(ResourceContract):
    target: str = Field(min_length=1)
    status: Literal["covered", "missing"]
    reason: str = Field(min_length=1, max_length=500)
    location: ResourceLocationV1 | None = None

    @model_validator(mode="after")
    def location_matches_status(self) -> "ResourceTargetCoverageV1":
        if self.status == "covered" and self.location is None:
            raise ValueError("covered target requires a current location")
        if self.status == "missing" and self.location is not None:
            raise ValueError("missing target cannot cite a location")
        return self


class ResourceReviewOutputV1(ResourceContract):
    binding: "ResourceReviewBindingV1"
    dimensions: ResourceDimensionsV1
    targets: list[ResourceTargetCoverageV1] = Field(min_length=1)
    hallucination_score: float = Field(ge=0, le=1)
    issues: list[ResourceIssueV1] = Field(default_factory=list, max_length=300)
    resolutions: list[ResourceResolutionV1] = Field(default_factory=list, max_length=300)
    reopen: list[ResourceReopenV1] = Field(default_factory=list, max_length=300)
    omitted_blocking_issues: bool
    # Assessment combined: complete per-question professional findings.  The
    # server maps them deterministically to issue ``finding_keys``.
    findings: list[ResourceFindingV1] = Field(default_factory=list, max_length=300)


class ResourceReviewInitialV1(ResourceReviewOutputV1):
    """Initial semantic review: no resolutions or reopen."""


class ResourceReviewRecheckV1(ResourceReviewOutputV1):
    """Recheck semantic review: resolves the parent version's open issues."""


class ResourceReviewBindingV1(ResourceContract):
    run_id: str = Field(min_length=1)
    resource_spec_id: str = Field(min_length=1)
    lineage_id: str = Field(min_length=1)
    resource_id: str = Field(min_length=1)
    resource_type: str = Field(min_length=1, max_length=64)
    version: int = Field(ge=1)
    text_exact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    structured_payload_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_exact_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparison_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    evidence_context_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    parent_evidence_context_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    policy_hash: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def exact_hash_matches_parts(self) -> "ResourceReviewBindingV1":
        # exact hash covers the persisted artifact (text + structured payload);
        # comparison hash covers the mechanical-id-normalized comparison
        # projection.  They are computed by the adapter and must differ in
        # meaning, not necessarily in value, so no equality is asserted here.
        return self


class ResourceIssueHistoryV1(ResourceContract):
    issue: ResourceIssueV1
    introduced_step_id: str = Field(min_length=1)
    introduced_version: int = Field(ge=1)
    status: Literal["open", "closed"]


class ResourceGateKeyV1(ResourceContract):
    gate_rule_id: str = Field(min_length=1, max_length=128)
    scope_locator: str = Field(min_length=1, max_length=256)
    failure_code: str = Field(min_length=1, max_length=64)


class ResourceProgramGateResultV1(ResourceContract):
    """Deterministic gate outcome recorded as a program-gate observation.

    ``new_issues`` carries the program-origin issues derived from ``keys`` for
    this version (only non-empty when the gate fails).  The migration of prior
    program issues is ``resolved_program_issues`` (key now passes) and
    ``still_open_program_issues`` (key still fails); a passed gate folds the
    whole migration into the model observation instead of a separate gate one.
    """

    rule_version: str = Field(min_length=1, max_length=64)
    passed: bool
    keys: list[ResourceGateKeyV1] = Field(default_factory=list, max_length=128)
    new_issues: list["ResourceIssueV1"] = Field(default_factory=list, max_length=128)
    # Program-origin issues closed by this gate run (their key now passes).
    resolved_program_issues: list[str] = Field(default_factory=list, max_length=300)
    still_open_program_issues: list[str] = Field(default_factory=list, max_length=300)
    # Model-origin open issues carried forward verbatim (semantic not run).
    carry_forward_model_issues: list[str] = Field(default_factory=list, max_length=300)
    blocked_reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def gate_shape(self) -> "ResourceProgramGateResultV1":
        if self.passed and self.keys:
            raise ValueError("a passed gate cannot have failure keys")
        if self.passed and self.new_issues:
            raise ValueError("a passed gate cannot introduce new issues")
        if not self.passed and not self.keys and not self.new_issues:
            raise ValueError("a failed gate must name its failure keys")
        if any(item.origin != "program_gate" for item in self.new_issues):
            raise ValueError("gate new issues must be program_gate origin")
        return self


class ResourceObservationV1(ResourceContract):
    """One ledger observation, discriminated by origin."""

    origin: Literal["program_gate", "model_review"]
    step_id: str = Field(min_length=1)
    binding: ResourceReviewBindingV1
    output_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    comparison_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_content_hash: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    revision_kind: Literal["ordinary", "claim"] = "ordinary"
    unchanged: bool
    consecutive_unchanged: int = Field(ge=0)
    characters_added: int = Field(ge=0)
    characters_removed: int = Field(ge=0)
    gate: ResourceProgramGateResultV1 | None = None
    output: ResourceReviewOutputV1 | None = None
    coverage_rate: float | None = Field(default=None, ge=0, le=1)
    decision: Literal["approve", "revise", "human_review"] | None = None

    @model_validator(mode="after")
    def observation_origin_shape(self) -> "ResourceObservationV1":
        if self.origin == "program_gate":
            if self.gate is None or self.output is not None or self.output_hash is not None:
                raise ValueError("program gate observation requires gate and forbids model output")
            if self.decision is not None or self.coverage_rate is not None:
                raise ValueError("program gate observation has no model decision")
            if self.gate.passed:
                raise ValueError("a passed gate is folded into the model observation")
            if self.unchanged and self.parent_content_hash is None:
                raise ValueError("unchanged program gate requires a parent")
        else:
            if self.output is None or self.output_hash is None:
                raise ValueError("model observation requires output")
            if self.decision is None or self.coverage_rate is None:
                raise ValueError("model observation requires derived decision and coverage")
            if self.binding != self.output.binding:
                raise ValueError("observation binding must match output binding")
            if self.gate is not None and not self.gate.passed:
                raise ValueError("a failed gate cannot accompany a model observation")
        return self


class ResourceLedgerV1(ResourceContract):
    schema_version: Literal["1.0"] = "1.0"
    binding: ResourceReviewBindingV1
    issues: list[ResourceIssueHistoryV1] = Field(default_factory=list)
    observations: list[ResourceObservationV1] = Field(min_length=1)
    carry_over: EvidenceContextCarryOverV1 | None = None

    @model_validator(mode="after")
    def validate_chain(self) -> "ResourceLedgerV1":
        if self.binding != self.observations[-1].binding:
            raise ValueError("ledger final binding mismatch")
        if len({entry.step_id for entry in self.observations}) != len(self.observations):
            raise ValueError("ledger duplicate observation step")
        if len({entry.issue.issue_id for entry in self.issues}) != len(self.issues):
            raise ValueError("ledger duplicate issue")
        carried = []
        if self.carry_over is not None:
            if self.carry_over.previous_evidence_snapshot_hash == self.binding.evidence_snapshot_hash:
                raise ValueError("carry-over does not change the evidence context")
            if self.binding.version != self.carry_over.previous_version + 1:
                raise ValueError("carry-over must start at the direct successor version")
            carried = [ResourceIssueHistoryV1.model_validate(item) for item in self.carry_over.open_issues]
            if any(item.status != "open" for item in carried):
                raise ValueError("carry-over may only carry open issues")
            if ([item.issue for item in self.issues[:len(carried)]]
                    != [item.issue for item in carried]):
                raise ValueError("carried issue definitions were rewritten")
        previous = None
        count = self.carry_over.consecutive_unchanged if self.carry_over is not None else 0
        reconstructed: dict[str, ResourceIssueHistoryV1] = {item.issue.issue_id: item for item in carried}
        for entry in self.observations:
            for key in ("run_id", "resource_spec_id", "lineage_id", "policy_hash",
                        "evidence_snapshot_hash", "resource_type",
                        "evidence_context_id", "parent_evidence_context_hash"):
                if getattr(entry.binding, key) != getattr(self.binding, key):
                    raise ValueError("ledger mixed frozen context")
            if previous is not None:
                if entry.binding.version != previous.binding.version + 1:
                    raise ValueError("ledger observation version chain mismatch")
                if entry.parent_content_hash != previous.binding.artifact_exact_hash:
                    raise ValueError("ledger observation parent chain mismatch")
                if entry.unchanged != (entry.comparison_hash == previous.comparison_hash):
                    raise ValueError("ledger unchanged observation mismatch")
            elif self.carry_over is not None:
                if entry.parent_content_hash != self.carry_over.previous_content_hash:
                    raise ValueError("ledger epoch opening parent mismatch")
                if entry.unchanged != (entry.comparison_hash == self.carry_over.previous_comparison_hash):
                    raise ValueError("ledger epoch opening unchanged mismatch")
            elif entry.parent_content_hash is not None or entry.unchanged:
                raise ValueError("initial observation cannot be a revision")
            if entry.origin == "model_review" and entry.revision_kind == "ordinary":
                count = count + 1 if entry.unchanged else 0
            if entry.consecutive_unchanged != count:
                raise ValueError("ledger unchanged count mismatch")
            if entry.origin == "program_gate":
                _reconstruct_program_gate(entry, reconstructed, self.binding)
            else:
                _reconstruct_model_review(entry, reconstructed, self.binding)
            previous = entry
        if list(reconstructed.values()) != self.issues:
            raise ValueError("ledger issue state disagrees with observations")
        return self


def derived_coverage_rate(targets) -> float:
    if not targets:
        raise ValueError("resource review has no frozen targets")
    return sum(item.status == "covered" for item in targets) / len(targets)


def model_issue_id(*, run_id: str, resource_spec_id: str, lineage_id: str, step_id: str, ordinal: int) -> str:
    """Stable cross-round identity for a model-origin issue (prefix ``ri_``)."""
    if ordinal < 1 or not all((run_id, resource_spec_id, lineage_id, step_id)):
        raise ValueError("invalid model issue identity")
    identity = json.dumps([run_id, resource_spec_id, lineage_id, step_id, ordinal],
                          ensure_ascii=False, separators=(",", ":"))
    return "ri_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def program_issue_id(*, run_id: str, resource_spec_id: str, gate_rule_id: str,
                     scope_locator: str, failure_code: str) -> str:
    """Stable per-slot identity for a program-gate issue (prefix ``rip_``).

    It does not depend on the step id, so the same structural slot failing on a
    later version reuses the same issue id.
    """
    if not all((run_id, resource_spec_id, gate_rule_id, scope_locator, failure_code)):
        raise ValueError("invalid program issue identity")
    identity = json.dumps([run_id, resource_spec_id, gate_rule_id, scope_locator, failure_code],
                          ensure_ascii=False, separators=(",", ":"))
    return "rip_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _reconstruct_program_gate(entry: ResourceObservationV1,
                              reconstructed: dict[str, ResourceIssueHistoryV1],
                              binding: ResourceReviewBindingV1) -> None:
    gate = entry.gate
    resolved = set(gate.resolved_program_issues)
    still_open = set(gate.still_open_program_issues)
    if resolved & still_open:
        raise ValueError("ledger program issue both resolved and still open")
    open_program = {key for key, value in reconstructed.items()
                    if value.status == "open" and value.issue.origin == "program_gate"}
    if open_program != resolved | still_open:
        raise ValueError("ledger program migration incomplete")
    for issue_id in resolved | still_open:
        history = reconstructed[issue_id]
        if history.issue.origin != "program_gate":
            raise ValueError("ledger program migration references a model issue")
    for issue_id in resolved:
        reconstructed[issue_id] = reconstructed[issue_id].model_copy(update={"status": "closed"})
    if len(gate.new_issues) != len(gate.keys):
        raise ValueError("ledger program gate keys and issues disagree")
    for key, issue in zip(gate.keys, gate.new_issues):
        expected = program_issue_id(run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
                                    gate_rule_id=key.gate_rule_id, scope_locator=key.scope_locator,
                                    failure_code=key.failure_code)
        if issue.issue_id != expected:
            raise ValueError("ledger program issue identity mismatch")
        if issue.code != key.failure_code or issue.blocking_rule != key.gate_rule_id:
            raise ValueError("ledger program issue key mismatch")
        if issue.issue_id in reconstructed:
            if reconstructed[issue.issue_id].issue.origin != "program_gate":
                raise ValueError("program issue identity collides with a model issue")
            reconstructed[issue.issue_id] = reconstructed[issue.issue_id].model_copy(update={"status": "open"})
            continue
        reconstructed[issue.issue_id] = ResourceIssueHistoryV1(
            issue=issue, introduced_step_id=entry.step_id,
            introduced_version=entry.binding.version, status="open")
    carried = set(gate.carry_forward_model_issues)
    open_model = {key for key, value in reconstructed.items()
                  if value.status == "open" and value.issue.origin == "model_review"}
    if open_model != carried:
        raise ValueError("ledger carry_forward incomplete")


def _reconstruct_model_review(entry: ResourceObservationV1,
                              reconstructed: dict[str, ResourceIssueHistoryV1],
                              binding: ResourceReviewBindingV1) -> None:
    if entry.gate is not None:
        gate = entry.gate
        open_program = {key for key, value in reconstructed.items()
                        if value.status == "open" and value.issue.origin == "program_gate"}
        if set(gate.resolved_program_issues) != open_program:
            raise ValueError("ledger passed-gate program migration incomplete")
        if gate.still_open_program_issues or gate.new_issues or gate.keys:
            raise ValueError("ledger passed-gate carries failures")
        for issue_id in gate.resolved_program_issues:
            reconstructed[issue_id] = reconstructed[issue_id].model_copy(update={"status": "closed"})
    open_model = {key for key, value in reconstructed.items()
                  if value.status == "open" and value.issue.origin == "model_review"}
    resolved = [item.issue_id for item in entry.output.resolutions]
    if len(set(resolved)) != len(resolved) or set(resolved) != open_model:
        raise ValueError("ledger resolution set mismatch")
    for item in entry.output.resolutions:
        if item.result in {"fixed", "false_positive"}:
            reconstructed[item.issue_id] = reconstructed[item.issue_id].model_copy(
                update={"status": "closed"})
    for item in entry.output.reopen:
        if item.issue_id not in reconstructed or reconstructed[item.issue_id].status != "closed":
            raise ValueError("ledger illegal reopen")
        reconstructed[item.issue_id] = reconstructed[item.issue_id].model_copy(
            update={"status": "open"})
    for ordinal, item in enumerate(entry.output.issues, 1):
        expected_id = model_issue_id(run_id=binding.run_id, resource_spec_id=binding.resource_spec_id,
                                     lineage_id=binding.lineage_id, step_id=entry.step_id, ordinal=ordinal)
        if item.issue_id != expected_id or item.issue_id in reconstructed:
            raise ValueError("ledger issue identity mismatch")
        reconstructed[item.issue_id] = ResourceIssueHistoryV1(
            issue=item, introduced_step_id=entry.step_id,
            introduced_version=entry.binding.version,
            status="open" if item.blocking else "closed")


def canonical_output_material(output: ResourceReviewOutputV1) -> bytes:
    def without_nulls(value):
        if isinstance(value, dict):
            return {key: without_nulls(item) for key, item in value.items() if item is not None}
        if isinstance(value, list):
            return [without_nulls(item) for item in value]
        return value
    return json.dumps(without_nulls(output.model_dump(mode="json")), ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def output_hash(output: ResourceReviewOutputV1) -> str:
    return hashlib.sha256(canonical_output_material(output)).hexdigest()
