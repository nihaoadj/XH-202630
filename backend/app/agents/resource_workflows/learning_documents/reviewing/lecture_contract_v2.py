"""Deterministic V2 checks and the single derived lecture decision.

V1 accepted a model-authored ``dimensions.coverage`` and then compared it with
the target list, which let one output contradict itself.  V2 removes that second
source: coverage is computed from ``targets`` only, and every non-pass semantic
dimension still has to name the concrete defect that justifies it.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.models.reviews.lecture_review import LectureIssueV1, LectureLocationV1, LectureReviewBindingV1
from app.models.reviews.lecture_review_v2 import (
    SEMANTIC_DIMENSIONS_V2,
    LectureIssueV2,
    LectureReviewOutputV2,
    derived_coverage_rate,
)

from .lecture_contract import comparison_hash, paragraph_heading_paths, paragraphs, text_hash
from .lecture_errors import LectureReviewValidationError, require


def issue_id_v2(*, run_id: str, resource_spec_id: str, lineage_id: str, step_id: str, ordinal: int) -> str:
    if ordinal < 1 or not all((run_id, resource_spec_id, lineage_id, step_id)):
        raise LectureReviewValidationError("ISSUE_ID_COLLISION", "issues", "invalid issue identity")
    material = json.dumps([run_id, resource_spec_id, lineage_id, step_id, ordinal],
                          ensure_ascii=False, separators=(",", ":"))
    return "li2_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def _validate_location(location: LectureLocationV1, text: dict[str, str], *, path: str) -> None:
    line = text.get(location.paragraph_id)
    if line is None or (location.quote is not None and location.quote not in line):
        raise LectureReviewValidationError("LOCATION_OUT_OF_BOUNDS", f"{path}.paragraph_id",
                                           "location must belong to the bound content")
    paths = paragraph_heading_paths("\n".join(text.values()))
    if location.heading_path != paths[location.paragraph_id]:
        raise LectureReviewValidationError("LOCATION_OUT_OF_BOUNDS", f"{path}.heading_path",
                                           "heading path must match the bound content")


def _validate_refs(refs, evidence: dict[str, str], *, path: str) -> None:
    if len({ref.evidence_id for ref in refs}) != len(refs):
        raise LectureReviewValidationError("EVIDENCE_REF_INVALID", f"{path}.evidence_refs",
                                           "duplicate evidence reference")
    if any(evidence.get(ref.evidence_id) != ref.excerpt_hash for ref in refs):
        raise LectureReviewValidationError("EVIDENCE_REF_INVALID", f"{path}.evidence_refs",
                                           "evidence reference outside the frozen snapshot")


@dataclass(frozen=True)
class LectureDecisionV2:
    decision: str
    open_issues: tuple[LectureIssueV2, ...]
    coverage_rate: float
    unchanged: bool


def validate_lecture_review_v2(
    *, output: LectureReviewOutputV2, binding: LectureReviewBindingV1,
    content: str, previous_content: str | None, targets: list[str],
    evidence_hashes: dict[str, str], teaching_rule_ids: set[str],
    old_open: tuple[LectureIssueV2, ...] = (), old_closed: tuple[LectureIssueV2, ...] = (),
    consecutive_unchanged: int = 0, count_unchanged: bool = True,
    coverage_threshold: float = 0.8,
) -> LectureDecisionV2:
    """Check identity and completeness; never treat hashes as semantic proof."""
    require(output.binding == binding and text_hash(content) == binding.content_hash,
            "BINDING_MISMATCH", "binding", "binding or content hash does not match the frozen resource")
    require(consecutive_unchanged >= 0, "BINDING_MISMATCH", "consecutive_unchanged", "invalid unchanged count")
    require(not output.omitted_blocking_issues, "OMITTED_BLOCKING_ISSUES", "omitted_blocking_issues",
            "a review that omitted blocking issues cannot be trusted")

    expected_targets = set(targets)
    returned_targets = [item.target for item in output.targets]
    require(bool(expected_targets), "TARGET_EMPTY", "targets", "the frozen resource has no goal")
    require(len(returned_targets) == len(set(returned_targets)), "TARGET_SET_INCOMPLETE", "targets",
            "each frozen goal must appear exactly once")
    require(set(returned_targets) == expected_targets, "TARGET_SET_INCOMPLETE", "targets",
            "returned goals must equal the frozen goal set")
    coverage = derived_coverage_rate(output.targets)

    if previous_content is None:
        require(not (old_open or old_closed or output.resolutions or output.reopen),
                "RESOLUTION_SET_INCOMPLETE", "resolutions",
                "an initial review cannot resolve issues from an earlier version")
    unchanged = previous_content is not None and comparison_hash(content) == comparison_hash(previous_content)
    current_lines, previous_lines = paragraphs(content), paragraphs(previous_content or "")
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
    require(len(set(reopened)) == len(reopened) and not (set(reopened) - {item.issue_id for item in old_closed}),
            "REOPEN_INVALID", "reopen", "only closed issues may be reopened, at most once each")
    for index, item in enumerate(output.reopen):
        _validate_location(item.current_location, current_lines, path=f"reopen[{index}].current_location")
        _validate_refs(item.evidence_refs, evidence_hashes, path=f"reopen[{index}]")

    new_ids = [item.issue_id for item in output.issues]
    require(len(set(new_ids)) == len(new_ids), "ISSUE_ID_DUPLICATED", "issues",
            "temporary issue identifiers must be unique")
    require(not (set(new_ids) & set(existing)), "ISSUE_ID_COLLISION", "issues",
            "a new issue cannot reuse an existing identifier")
    for index, issue in enumerate(output.issues):
        _validate_location(issue.location, current_lines, path=f"issues[{index}].location")
        _validate_refs(issue.evidence_refs, evidence_hashes, path=f"issues[{index}]")
        if issue.teaching_rule_id:
            require(issue.teaching_rule_id in teaching_rule_ids, "TEACHING_RULE_UNKNOWN",
                    f"issues[{index}].teaching_rule_id", "unknown teaching rule")
    for index, resolution in enumerate(output.resolutions):
        _validate_refs(resolution.evidence_refs, evidence_hashes, path=f"resolutions[{index}]")
        if resolution.current_location is not None:
            _validate_location(resolution.current_location, current_lines,
                               path=f"resolutions[{index}].current_location")
        if resolution.previous_location is not None:
            _validate_location(resolution.previous_location, previous_lines,
                               path=f"resolutions[{index}].previous_location")
        require(not (unchanged and resolution.result == "fixed"), "UNCHANGED_FIXED",
                f"resolutions[{index}].result", "unchanged content cannot be reported fixed")

    open_issues = tuple(item for item in old_open if resolutions[item.issue_id].result in {"still_open", "unverifiable"})
    open_issues += tuple(item for item in old_closed if item.issue_id in reopened)
    open_issues += tuple(item for item in output.issues if item.blocking)
    require(len(open_issues) <= 24, "OPEN_ISSUE_LIMIT", "issues", "open issue limit exceeded")

    missing_targets = {item.target for item in output.targets if item.status == "missing"}
    # Applies to every new issue, blocking or advisory: an advisory coverage note
    # must not quietly contradict the per-target verdicts either.
    for index, issue in enumerate(output.issues):
        linked = set(issue.affected_target_ids)
        if issue.dimension == "coverage":
            require(linked <= missing_targets, "COVERAGE_TARGET_INVALID",
                    f"issues[{index}].affected_target_ids",
                    "a coverage issue may only affect frozen goals that this review reports missing")
            require(bool(linked) or not issue.blocking, "COVERAGE_TARGET_INVALID",
                    f"issues[{index}].affected_target_ids",
                    "a blocking coverage issue must name the goals it affects")
        else:
            require(not linked, "COVERAGE_TARGET_INVALID", f"issues[{index}].affected_target_ids",
                    "only coverage issues may name affected goals")
    for target in output.targets:
        if target.status != "missing":
            continue
        require(any(issue.dimension == "coverage" and issue.blocking and target.target in issue.affected_target_ids
                    for issue in open_issues),
                "TARGET_LINK_MISSING", f"targets[{target.target}]",
                "a missing goal requires a concrete blocking coverage issue with a requirement and acceptance")

    dimensions = output.dimensions.model_dump()
    for dimension in SEMANTIC_DIMENSIONS_V2:
        matching = any(issue.dimension == dimension and issue.blocking for issue in open_issues)
        if dimensions[dimension] != "pass":
            require(matching, "DIMENSION_ISSUE_CONFLICT", f"dimensions.{dimension}",
                    "a non-pass judgement requires a blocking issue of that dimension")
        else:
            require(not matching, "DIMENSION_ISSUE_CONFLICT", f"dimensions.{dimension}",
                    "a pass judgement cannot coexist with a blocking issue of that dimension")

    factual_open = any(issue.dimension == "factual_evidence" or issue.code in {"factual_risk", "evidence_gap"}
                       for issue in open_issues)
    high_risk = dimensions["factual_evidence"] != "pass" or factual_open
    require((output.hallucination_score >= 0.2) == high_risk, "RISK_SCORE_CONFLICT", "hallucination_score",
            "risk score must agree with the factual findings")

    if not open_issues and all(status == "pass" for status in dimensions.values()) and coverage >= coverage_threshold:
        decision = "approve"
    elif any(item.executability == "evidence_insufficient" for item in open_issues):
        decision = "human_review"
    elif count_unchanged and unchanged and consecutive_unchanged + 1 >= 2:
        decision = "human_review"
    else:
        decision = "revise"
    return LectureDecisionV2(decision, open_issues, coverage, unchanged)


def as_v1_issue_view(issue: LectureIssueV2) -> LectureIssueV1:
    """Read-only projection for code paths that still key on V1 issue shape."""
    return LectureIssueV1.model_validate({k: v for k, v in issue.model_dump(mode="json").items()
                                          if k != "affected_target_ids"})
