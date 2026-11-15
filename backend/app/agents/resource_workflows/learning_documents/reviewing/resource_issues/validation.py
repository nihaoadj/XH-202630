"""Typed validation failures for the generic resource reviewer.

Correction decisions are made from stable codes, never from exception text.
Only codes in ``CORRECTABLE_CODES`` describe a self-consistent model output
that contradicts another part of the same output; every other code means the
run must stop unpublished.
"""

from __future__ import annotations

CORRECTABLE_CODES = frozenset({
    "TARGET_SET_INCOMPLETE",
    "TARGET_LINK_MISSING",
    "COVERAGE_TARGET_INVALID",
    "DIMENSION_ISSUE_CONFLICT",
    "RISK_SCORE_CONFLICT",
    "RESOLUTION_SET_INCOMPLETE",
    "ISSUE_ID_DUPLICATED",
    "FINDING_KEY_INCOMPLETE",
})

NON_CORRECTABLE_CODES = (
    "BINDING_MISMATCH", "OMITTED_BLOCKING_ISSUES", "LOCATION_OUT_OF_BOUNDS",
    "EVIDENCE_REF_INVALID", "TEACHING_RULE_UNKNOWN", "UNCHANGED_FIXED",
    "REOPEN_INVALID", "ISSUE_ID_COLLISION", "OPEN_ISSUE_LIMIT", "TARGET_EMPTY",
    "ISSUE_LIMIT", "ORIGIN_INVALID", "FINDING_INVALID",
)


class ValidationError(ValueError):
    """A stable, bounded description of one invalid review result."""

    def __init__(self, code: str, path: str, hint: str):
        self.code = code
        self.path = path
        self.hint = hint
        super().__init__(f"{code} at {path}: {hint}")

    @property
    def correctable(self) -> bool:
        return self.code in CORRECTABLE_CODES


def require(condition: bool, code: str, path: str, hint: str) -> None:
    if not condition:
        raise ValidationError(code=code, path=path, hint=hint)


from dataclasses import dataclass  # noqa: E402

from app.models.reviews.resource_review import (  # noqa: E402
    ResourceIssueV1,
    ResourceReviewBindingV1,
    ResourceReviewOutputV1,
    SEMANTIC_DIMENSIONS,
    derived_coverage_rate,
)
from .adapters.base import LocationIndex, validate_evidence_refs  # noqa: E402


@dataclass(frozen=True)
class ValidationOutcome:
    open_issues: tuple[ResourceIssueV1, ...]
    coverage_rate: float
    unchanged: bool
    has_evidence_insufficient: bool
    dimensions_pass: bool


def validate_resource_review(
    *,
    output: ResourceReviewOutputV1,
    binding: ResourceReviewBindingV1,
    material,
    adapter,
    previous_comparison_hash: str | None,
    old_open: tuple[ResourceIssueV1, ...] = (),
    old_closed: tuple[ResourceIssueV1, ...] = (),
    parent_material=None,
) -> ValidationOutcome:
    """Identity, completeness, evidence, location, coverage and finding checks.

    Never treats hashes as semantic proof: this validates the model's answer is
    internally consistent and bound to the frozen material; the semantic
    correctness of findings stays with the frozen evaluation.
    """
    require(output.binding == binding, "BINDING_MISMATCH", "binding",
            "binding does not match the frozen resource")
    require(material.artifact_exact_hash == binding.artifact_exact_hash,
            "BINDING_MISMATCH", "binding.artifact_exact_hash",
            "artifact exact hash does not match the bound content")
    require(not output.omitted_blocking_issues, "OMITTED_BLOCKING_ISSUES",
            "omitted_blocking_issues", "a review that omitted blocking issues cannot be trusted")

    expected_targets = set(material.targets)
    returned_targets = [item.target for item in output.targets]
    require(bool(expected_targets), "TARGET_EMPTY", "targets", "the frozen resource has no goal")
    require(len(returned_targets) == len(set(returned_targets)), "TARGET_SET_INCOMPLETE", "targets",
            "each frozen goal must appear exactly once")
    require(set(returned_targets) == expected_targets, "TARGET_SET_INCOMPLETE", "targets",
            "returned goals must equal the frozen goal set")
    coverage = derived_coverage_rate(output.targets)

    if previous_comparison_hash is None:
        require(not (old_open or old_closed or output.resolutions or output.reopen),
                "RESOLUTION_SET_INCOMPLETE", "resolutions",
                "an initial review cannot resolve issues from an earlier version")
    unchanged = previous_comparison_hash is not None and material.comparison_hash == previous_comparison_hash

    existing = {item.issue_id: item for item in (*old_open, *old_closed)}
    require(len(existing) == len(old_open) + len(old_closed), "ISSUE_ID_COLLISION", "issues",
            "duplicate existing issue identity")
    resolutions = {item.issue_id: item for item in output.resolutions}
    require(len(resolutions) == len(output.resolutions), "RESOLUTION_SET_INCOMPLETE", "resolutions",
            "old issue resolutions must not repeat")
    require(set(resolutions) == {item.issue_id for item in old_open},
            "RESOLUTION_SET_INCOMPLETE", "resolutions",
            "every open issue of the parent version must be resolved exactly once")
    reopened = [item.issue_id for item in output.reopen]
    require(len(set(reopened)) == len(reopened)
            and not (set(reopened) - {item.issue_id for item in old_closed}),
            "REOPEN_INVALID", "reopen", "only closed issues may be reopened, at most once each")
    for index, item in enumerate(output.reopen):
        material.index.validate(item.current_location, path=f"reopen[{index}].current_location")
        validate_evidence_refs(item.evidence_refs, material.evidence_hashes, path=f"reopen[{index}]")

    new_ids = [item.issue_id for item in output.issues]
    require(len(set(new_ids)) == len(new_ids), "ISSUE_ID_DUPLICATED", "issues",
            "temporary issue identifiers must be unique")
    require(not (set(new_ids) & set(existing)), "ISSUE_ID_COLLISION", "issues",
            "a new issue cannot reuse an existing identifier")
    for index, issue in enumerate(output.issues):
        require(issue.origin == "model_review", "ORIGIN_INVALID", f"issues[{index}].origin",
                "a model must not self-declare a program_gate origin")
        material.index.validate(issue.location, path=f"issues[{index}].location")
        validate_evidence_refs(issue.evidence_refs, material.evidence_hashes, path=f"issues[{index}]")
        if issue.teaching_rule_id:
            require(issue.teaching_rule_id in material.rule_ids, "TEACHING_RULE_UNKNOWN",
                    f"issues[{index}].teaching_rule_id", "unknown teaching rule")
    for index, resolution in enumerate(output.resolutions):
        validate_evidence_refs(resolution.evidence_refs, material.evidence_hashes,
                               path=f"resolutions[{index}]")
        if resolution.current_location is not None:
            material.index.validate(resolution.current_location,
                                    path=f"resolutions[{index}].current_location")
        if resolution.previous_location is not None:
            require(parent_material is not None, "BINDING_MISMATCH", "parent_material",
                    "previous location requires the verified parent artifact")
            parent_material.index.validate(resolution.previous_location,
                                           path=f"resolutions[{index}].previous_location")
        require(not (unchanged and resolution.result == "fixed"), "UNCHANGED_FIXED",
                f"resolutions[{index}].result", "unchanged content cannot be reported fixed")

    def current_issue(issue, observation):
        refs = observation.current_check_refs
        if issue.finding_keys:
            require(bool(refs), "FINDING_KEY_INCOMPLETE", "resolutions.current_check_refs",
                    "an open professional issue requires current-version check references")
        return issue.model_copy(update={"location": observation.current_location or issue.location,
                                        "finding_keys": refs if issue.finding_keys or refs else issue.finding_keys})
    open_issues = tuple(current_issue(item, resolutions[item.issue_id]) for item in old_open
                        if resolutions[item.issue_id].result in {"still_open", "unverifiable"})
    reopening = {item.issue_id: item for item in output.reopen}
    open_issues += tuple(current_issue(item, reopening[item.issue_id]) for item in old_closed if item.issue_id in reopened)
    open_issues += tuple(item for item in output.issues if item.blocking)
    adapter.validate_findings(output=output, material=material, open_issues=open_issues)
    require(len(open_issues) <= 24, "OPEN_ISSUE_LIMIT", "issues", "open issue limit exceeded")

    missing_targets = {item.target for item in output.targets if item.status == "missing"}
    for index, issue in enumerate(output.issues):
        linked = set(issue.affected_target_ids)
        if issue.dimension == "coverage":
            require(linked <= missing_targets, "COVERAGE_TARGET_INVALID",
                    f"issues[{index}].affected_target_ids",
                    "a coverage issue may only affect frozen goals reported missing")
            require(bool(linked) or not issue.blocking, "COVERAGE_TARGET_INVALID",
                    f"issues[{index}].affected_target_ids",
                    "a blocking coverage issue must name the goals it affects")
        else:
            require(not linked, "COVERAGE_TARGET_INVALID", f"issues[{index}].affected_target_ids",
                    "only coverage issues may name affected goals")
    for target in output.targets:
        if target.status != "missing":
            continue
        require(any(issue.dimension == "coverage" and issue.blocking
                    and target.target in issue.affected_target_ids for issue in open_issues),
                "TARGET_LINK_MISSING", f"targets[{target.target}]",
                "a missing goal requires a concrete blocking coverage issue")

    dimensions = output.dimensions.model_dump()
    for dimension in SEMANTIC_DIMENSIONS:
        matching = any(issue.dimension == dimension and issue.blocking for issue in open_issues)
        if dimensions[dimension] != "pass":
            require(matching, "DIMENSION_ISSUE_CONFLICT", f"dimensions.{dimension}",
                    "a non-pass judgement requires a blocking issue of that dimension")
        else:
            require(not matching, "DIMENSION_ISSUE_CONFLICT", f"dimensions.{dimension}",
                    "a pass judgement cannot coexist with a blocking issue of that dimension")

    factual_open = any(issue.dimension == "factual_evidence"
                       or issue.code in {"factual_risk", "evidence_gap"} for issue in open_issues)
    high_risk = dimensions["factual_evidence"] != "pass" or factual_open
    require((output.hallucination_score >= 0.2) == high_risk, "RISK_SCORE_CONFLICT",
            "hallucination_score", "risk score must agree with the factual findings")

    return ValidationOutcome(
        open_issues=open_issues, coverage_rate=coverage, unchanged=unchanged,
        has_evidence_insufficient=any(item.executability == "evidence_insufficient"
                                      for item in open_issues),
        dimensions_pass=all(status == "pass" for status in dimensions.values()),
    )
