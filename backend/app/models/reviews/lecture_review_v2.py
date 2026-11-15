"""Version 2 lecture review contracts.

Changes against V1 are deliberately narrow and mechanical:

* the model no longer states an overall coverage verdict; only per-target
  ``covered``/``missing`` remain, and the program derives the rate;
* coverage issues must name the frozen targets they affect, so a missing target
  cannot be left without a concrete, executable requirement;
* the other three dimensions keep their independent semantic judgement.

A frozen V1 record is never reinterpreted through these models.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from .evidence_context import EvidenceContextCarryOverV1
from .lecture_review import (
    LectureContract,
    LectureEvidenceRefV1,
    LectureLocationV1,
    LectureResolutionV1,
    LectureReopenV1,
    LectureReviewBindingV1,
)

SEMANTIC_DIMENSIONS_V2 = ("factual_evidence", "difficulty", "self_contained")
ALL_ISSUE_DIMENSIONS_V2 = ("factual_evidence", "coverage", "difficulty", "self_contained")


class LectureReviewPolicyV2(LectureContract):
    schema_version: Literal["2.0"] = "2.0"
    strategy: Literal["lecture_issue_v2"] = "lecture_issue_v2"
    initial_profile: Literal["lecture_initial_v2"] = "lecture_initial_v2"
    recheck_profile: Literal["lecture_recheck_v2"] = "lecture_recheck_v2"
    rubric_version: Literal["lecture-rubric-v2"] = "lecture-rubric-v2"
    normalization_version: Literal["crlf-lf-v1"] = "crlf-lf-v1"
    max_open_issues: Literal[24] = 24
    max_new_issues_per_review: Literal[12] = 12
    max_consecutive_unchanged: Literal[2] = 2
    # Program-owned threshold. The model never receives or returns it as a
    # verdict; it only bounds which derived decisions are available.
    coverage_threshold: Literal[0.8] = 0.8
    # Frozen from the reviewer options that were actually active at creation.
    max_physical_attempts: int = Field(ge=1, le=3)
    business_correction_limit: Literal[1] = 1
    context_tokens: int = Field(gt=0)
    max_output_tokens: int = Field(gt=0)

    @model_validator(mode="after")
    def window_has_input_space(self):
        if self.max_output_tokens >= self.context_tokens:
            raise ValueError("review output reserve exhausts context window")
        return self


class LectureDimensionsV2(LectureContract):
    """Three independent semantic judgements; coverage is not one of them."""

    factual_evidence: Literal["pass", "fail", "insufficient"]
    difficulty: Literal["pass", "fail", "insufficient"]
    self_contained: Literal["pass", "fail", "insufficient"]


class LectureTargetCoverageV2(LectureContract):
    target: str = Field(min_length=1)
    status: Literal["covered", "missing"]
    reason: str = Field(min_length=1, max_length=500)
    location: LectureLocationV1 | None = None

    @model_validator(mode="after")
    def location_matches_status(self):
        # A covered target must point at the text that teaches it; a missing one
        # must not fabricate a quote for content that does not exist.
        if self.status == "covered" and self.location is None:
            raise ValueError("covered target requires a current location")
        if self.status == "missing" and self.location is not None:
            raise ValueError("missing target cannot cite a location")
        return self


class LectureIssueV2(LectureContract):
    issue_id: str = Field(min_length=1)
    code: str = Field(min_length=1, max_length=64)
    severity: Literal["low", "medium", "high", "critical"]
    blocking: bool
    blocking_rule: str | None = None
    dimension: Literal["factual_evidence", "coverage", "difficulty", "self_contained"]
    # Only coverage issues carry target links; every other dimension is about
    # the text as a whole, not about a specific goal.
    affected_target_ids: list[str] = Field(default_factory=list, max_length=12)
    location: LectureLocationV1
    impact: str = Field(min_length=1, max_length=500)
    requirement: str = Field(min_length=1, max_length=1000)
    acceptance: str = Field(min_length=1, max_length=1000)
    criteria_version: int = Field(ge=1)
    path: Literal["add_from_evidence", "reorganize_existing", "remove_or_narrow", "synthetic_example",
                  "replace_or_drop_exercise", "evidence_insufficient"]
    evidence_refs: list[LectureEvidenceRefV1] = Field(default_factory=list, max_length=24)
    teaching_rule_id: str | None = None
    executability: Literal["executable", "evidence_insufficient"]
    rationale: str = Field(min_length=1, max_length=1000)

    @model_validator(mode="after")
    def valid_issue(self):
        if self.severity in {"high", "critical"} and not self.blocking:
            raise ValueError("high severity issue must block")
        if self.blocking and not self.blocking_rule:
            raise ValueError("blocking issue requires a blocking rule")
        if not self.evidence_refs and not self.teaching_rule_id:
            raise ValueError("issue requires evidence or a teaching rule")
        if self.path in {"add_from_evidence", "synthetic_example"} and not self.evidence_refs:
            raise ValueError("technical addition requires frozen evidence")
        if (self.path == "evidence_insufficient") != (self.executability == "evidence_insufficient"):
            raise ValueError("path and executability disagree")
        if len({item for item in self.affected_target_ids}) != len(self.affected_target_ids):
            raise ValueError("duplicate affected target")
        if self.dimension == "coverage":
            if self.blocking and not self.affected_target_ids:
                raise ValueError("blocking coverage issue requires affected targets")
        elif self.affected_target_ids:
            raise ValueError("only coverage issues may affect specific targets")
        return self


class LectureReviewOutputV2(LectureContract):
    binding: LectureReviewBindingV1
    dimensions: LectureDimensionsV2
    targets: list[LectureTargetCoverageV2] = Field(min_length=1)
    hallucination_score: float = Field(ge=0, le=1)
    issues: list[LectureIssueV2] = Field(max_length=12)
    resolutions: list[LectureResolutionV1] = Field(default_factory=list, max_length=24)
    reopen: list[LectureReopenV1] = Field(default_factory=list, max_length=24)
    omitted_blocking_issues: bool


def derived_coverage_rate(targets) -> float:
    """The single source of the coverage rate: covered count over frozen goals."""
    if not targets:
        raise ValueError("lecture review has no frozen targets")
    return sum(item.status == "covered" for item in targets) / len(targets)


class LectureIssueHistoryV2(LectureContract):
    issue: LectureIssueV2
    introduced_step_id: str = Field(min_length=1)
    introduced_version: int = Field(ge=1)
    status: Literal["open", "closed"]


class LectureObservationV2(LectureContract):
    step_id: str = Field(min_length=1)
    binding: LectureReviewBindingV1
    output_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    comparison_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    parent_content_hash: str | None
    revision_kind: Literal["ordinary", "claim"] = "ordinary"
    unchanged: bool
    consecutive_unchanged: int = Field(ge=0)
    characters_added: int = Field(ge=0)
    characters_removed: int = Field(ge=0)
    output: LectureReviewOutputV2
    # Derived, not model-authored. Persisted so a replay recomputes the same
    # value instead of trusting a second summary.
    coverage_rate: float = Field(ge=0, le=1)
    decision: Literal["approve", "revise", "human_review"]

    @model_validator(mode="after")
    def validate_observation(self):
        def without_nulls(value):
            if isinstance(value, dict):
                return {key: without_nulls(item) for key, item in value.items() if item is not None}
            if isinstance(value, list):
                return [without_nulls(item) for item in value]
            return value
        material = json.dumps(without_nulls(self.output.model_dump(mode="json")), ensure_ascii=False,
                              sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        if self.binding != self.output.binding or hashlib.sha256(material).hexdigest() != self.output_hash:
            raise ValueError("lecture observation output hash or binding mismatch")
        if self.coverage_rate != derived_coverage_rate(self.output.targets):
            raise ValueError("lecture observation coverage rate is not the derived value")
        return self


class LectureLedgerV2(LectureContract):
    schema_version: Literal["2.0"] = "2.0"
    binding: LectureReviewBindingV1
    issues: list[LectureIssueHistoryV2] = Field(default_factory=list)
    observations: list[LectureObservationV2] = Field(min_length=1)
    carry_over: EvidenceContextCarryOverV1 | None = None

    @model_validator(mode="after")
    def validate_chain(self):
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
            carried = [LectureIssueHistoryV2.model_validate(item) for item in self.carry_over.open_issues]
            if any(item.status != "open" for item in carried):
                raise ValueError("carry-over may only carry open issues")
            if ([item.issue for item in self.issues[:len(carried)]]
                    != [item.issue for item in carried]):
                raise ValueError("carried issue definitions were rewritten")
        previous = None
        count = self.carry_over.consecutive_unchanged if self.carry_over is not None else 0
        reconstructed = {item.issue.issue_id: item for item in carried}
        for entry in self.observations:
            for key in ("run_id", "resource_spec_id", "lineage_id", "policy_hash",
                        "evidence_snapshot_hash", "evidence_context_id", "parent_evidence_context_hash"):
                if getattr(entry.binding, key) != getattr(self.binding, key):
                    raise ValueError("ledger mixed frozen context")
            if previous is not None:
                if entry.binding.version != previous.binding.version + 1 or entry.parent_content_hash != previous.binding.content_hash:
                    raise ValueError("ledger observation version chain mismatch")
                if entry.unchanged != (entry.comparison_hash == previous.comparison_hash):
                    raise ValueError("ledger unchanged observation mismatch")
            elif self.carry_over is not None:
                if entry.parent_content_hash != self.carry_over.previous_content_hash:
                    raise ValueError("ledger epoch opening parent mismatch")
                if entry.unchanged != (entry.comparison_hash == self.carry_over.previous_comparison_hash):
                    raise ValueError("ledger epoch opening unchanged mismatch")
            elif entry.parent_content_hash is not None or entry.unchanged:
                raise ValueError("initial observation cannot be a revision")
            if entry.revision_kind == "ordinary":
                count = count + 1 if entry.unchanged else 0
            if entry.consecutive_unchanged != count:
                raise ValueError("ledger unchanged count mismatch")
            open_ids = {key for key, value in reconstructed.items() if value.status == "open"}
            resolved = [item.issue_id for item in entry.output.resolutions]
            if len(set(resolved)) != len(resolved) or set(resolved) != open_ids:
                raise ValueError("ledger resolution set mismatch")
            for item in entry.output.resolutions:
                if item.result in {"fixed", "false_positive"}:
                    reconstructed[item.issue_id] = reconstructed[item.issue_id].model_copy(update={"status": "closed"})
            for item in entry.output.reopen:
                if item.issue_id not in reconstructed or reconstructed[item.issue_id].status != "closed":
                    raise ValueError("ledger illegal reopen")
                reconstructed[item.issue_id] = reconstructed[item.issue_id].model_copy(update={"status": "open"})
            for ordinal, item in enumerate(entry.output.issues, 1):
                identity = json.dumps([self.binding.run_id, self.binding.resource_spec_id,
                    self.binding.lineage_id, entry.step_id, ordinal], ensure_ascii=False, separators=(",", ":"))
                expected_id = "li2_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()
                if item.issue_id != expected_id or item.issue_id in reconstructed:
                    raise ValueError("ledger issue identity mismatch")
                reconstructed[item.issue_id] = LectureIssueHistoryV2(
                    issue=item, introduced_step_id=entry.step_id,
                    introduced_version=entry.binding.version, status="open" if item.blocking else "closed")
            previous = entry
        if list(reconstructed.values()) != self.issues:
            raise ValueError("ledger issue state disagrees with observations")
        return self
