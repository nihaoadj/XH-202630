"""Deterministic identity, evidence, completeness and lecture decision checks."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from app.models.reviews.lecture_review import (
    LectureIssueV1,
    LectureLocationV1,
    LectureReviewBindingV1,
    LectureReviewOutputV1,
)


def text_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def comparison_hash(content: str) -> str:
    return text_hash(content.replace("\r\n", "\n"))


def issue_id(*, run_id: str, resource_spec_id: str, lineage_id: str, step_id: str, ordinal: int) -> str:
    if ordinal < 1 or not all((run_id, resource_spec_id, lineage_id, step_id)):
        raise ValueError("invalid issue identity")
    material = json.dumps([run_id, resource_spec_id, lineage_id, step_id, ordinal],
                          ensure_ascii=False, separators=(",", ":"))
    return "li_" + hashlib.sha256(material.encode("utf-8")).hexdigest()


def paragraphs(content: str) -> dict[str, str]:
    """Expose stable line locations for a single exact version of the text."""
    return {f"p{number:06d}": line for number, line in
            enumerate(content.replace("\r\n", "\n").split("\n"), 1)}


def _validate_location(location: LectureLocationV1, text: dict[str, str]) -> None:
    line = text.get(location.paragraph_id)
    if line is None or (location.quote is not None and location.quote not in line):
        raise ValueError("location does not belong to the bound content")
    paths = paragraph_heading_paths("\n".join(text.values()))
    if location.heading_path != paths[location.paragraph_id]:
        raise ValueError("location heading path does not match bound content")


def paragraph_heading_paths(content: str) -> dict[str, list[str]]:
    headings = []
    fence = None
    paths = {}
    for paragraph_id, paragraph in paragraphs(content).items():
        stripped = paragraph.lstrip()
        if stripped.startswith(("```", "~~~")):
            marker = stripped[:3]
            fence = None if fence == marker else marker if fence is None else fence
        marker, separator, title = paragraph.partition(" ")
        if fence is None and separator and marker and len(marker) <= 6 and set(marker) == {"#"}:
            level = len(marker)
            headings = [(depth, value) for depth, value in headings if depth < level]
            headings.append((level, title.strip()))
        paths[paragraph_id] = [title for _, title in headings]
    return paths


def _validate_refs(refs, evidence: dict[str, str]) -> None:
    if len({ref.evidence_id for ref in refs}) != len(refs):
        raise ValueError("duplicate evidence reference")
    if any(evidence.get(ref.evidence_id) != ref.excerpt_hash for ref in refs):
        raise ValueError("evidence reference outside frozen snapshot")


@dataclass(frozen=True)
class LectureDecision:
    decision: str
    open_issues: tuple[LectureIssueV1, ...]
    coverage_rate: float
    unchanged: bool


def validate_lecture_review(
    *, output: LectureReviewOutputV1, binding: LectureReviewBindingV1,
    content: str, previous_content: str | None, targets: list[str],
    evidence_hashes: dict[str, str], teaching_rule_ids: set[str],
    old_open: tuple[LectureIssueV1, ...] = (), old_closed: tuple[LectureIssueV1, ...] = (),
    consecutive_unchanged: int = 0, count_unchanged: bool = True,
) -> LectureDecision:
    """Check identity and completeness; never treat hashes as semantic proof."""
    if output.binding != binding or text_hash(content) != binding.content_hash:
        raise ValueError("review binding or content hash mismatch")
    if consecutive_unchanged < 0:
        raise ValueError("invalid unchanged count")
    if output.omitted_blocking_issues:
        raise ValueError("review omitted blocking issues")
    expected_targets = set(targets)
    returned_targets = [item.target for item in output.targets]
    if not expected_targets or len(returned_targets) != len(set(returned_targets)) or set(returned_targets) != expected_targets:
        raise ValueError("target coverage must match frozen goals")
    coverage = sum(item.status == "covered" for item in output.targets) / len(expected_targets)
    if coverage < 0.8 and output.dimensions.coverage == "pass":
        raise ValueError("coverage dimension conflicts with target coverage")
    if previous_content is None and (old_open or old_closed or output.resolutions or output.reopen):
        raise ValueError("historical review requires previous content")
    unchanged = previous_content is not None and comparison_hash(content) == comparison_hash(previous_content)
    current_lines, previous_lines = paragraphs(content), paragraphs(previous_content or "")
    existing = {item.issue_id: item for item in (*old_open, *old_closed)}
    if len(existing) != len(old_open) + len(old_closed):
        raise ValueError("duplicate existing issue id")
    resolutions = {item.issue_id: item for item in output.resolutions}
    if len(resolutions) != len(output.resolutions) or set(resolutions) != {item.issue_id for item in old_open}:
        raise ValueError("old issue resolutions incomplete or duplicated")
    reopened = [item.issue_id for item in output.reopen]
    if len(set(reopened)) != len(reopened) or set(reopened) - {item.issue_id for item in old_closed}:
        raise ValueError("invalid reopened issue")
    for item in output.reopen:
        _validate_location(item.current_location, current_lines)
        _validate_refs(item.evidence_refs, evidence_hashes)
    new_ids = [item.issue_id for item in output.issues]
    if len(set(new_ids)) != len(new_ids) or set(new_ids) & set(existing):
        raise ValueError("new issue id collision")
    for issue in output.issues:
        _validate_location(issue.location, current_lines)
        _validate_refs(issue.evidence_refs, evidence_hashes)
        if issue.teaching_rule_id and issue.teaching_rule_id not in teaching_rule_ids:
            raise ValueError("unknown teaching rule")
    for resolution in output.resolutions:
        _validate_refs(resolution.evidence_refs, evidence_hashes)
        if resolution.current_location is not None:
            _validate_location(resolution.current_location, current_lines)
        if resolution.previous_location is not None:
            _validate_location(resolution.previous_location, previous_lines)
        if unchanged and resolution.result == "fixed":
            raise ValueError("unchanged content cannot be reported fixed")
    open_issues = tuple(item for item in old_open if resolutions[item.issue_id].result in {"still_open", "unverifiable"})
    open_issues += tuple(item for item in old_closed if item.issue_id in reopened)
    open_issues += tuple(item for item in output.issues if item.blocking)
    if len(open_issues) > 24:
        raise ValueError("open issue limit exceeded")
    dimensions = output.dimensions.model_dump()
    for dimension, status in dimensions.items():
        if status != "pass" and not any(issue.dimension == dimension and issue.blocking for issue in open_issues):
            raise ValueError("failed dimension lacks a blocking issue")
    factual_open = any(item.dimension == "factual_evidence" or item.code in {"factual_risk", "evidence_gap"}
                       for item in open_issues)
    high_risk = dimensions["factual_evidence"] != "pass" or factual_open
    if (output.hallucination_score >= 0.2) != high_risk:
        raise ValueError("risk score conflicts with factual findings")
    if not open_issues and all(status == "pass" for status in dimensions.values()):
        decision = "approve"
    elif any(item.executability == "evidence_insufficient" for item in open_issues):
        decision = "human_review"
    elif count_unchanged and unchanged and consecutive_unchanged + 1 >= 2:
        decision = "human_review"
    else:
        decision = "revise"
    return LectureDecision(decision, open_issues, coverage, unchanged)
