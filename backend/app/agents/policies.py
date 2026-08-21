"""Deterministic review and publication policies.

The reviewer model may recommend a decision, but it never owns the release gate.
"""

from __future__ import annotations

from typing import Any, Iterable

from app.models.workflow import ReviewDecision


BLOCKING_SEVERITIES = frozenset({"high", "critical"})


def decide_review(
    review: dict[str, Any],
    *,
    valid_source_refs: bool,
    valid_revision_instructions: bool,
) -> ReviewDecision:
    """Convert a validated model recommendation into a fail-closed decision."""

    if not valid_source_refs:
        return ReviewDecision.HUMAN_REVIEW
    try:
        requested = ReviewDecision(str(review.get("decision")))
    except ValueError:
        return ReviewDecision.HUMAN_REVIEW
    if requested == ReviewDecision.HUMAN_REVIEW:
        return requested
    if requested == ReviewDecision.REJECT:
        return requested

    issues = review.get("issues") or []
    has_blocking_issue = any(
        isinstance(issue, dict) and issue.get("severity") in BLOCKING_SEVERITIES
        for issue in issues
    )
    if (
        requested == ReviewDecision.APPROVE
        and float(review.get("hallucination_score", 1.0)) < 0.2
        and bool(review.get("difficulty_match", False))
        and float(review.get("coverage_rate", 0.0)) >= 0.8
        and not has_blocking_issue
    ):
        return ReviewDecision.APPROVE
    if valid_revision_instructions and review.get("revision_instructions"):
        return ReviewDecision.REVISE
    return ReviewDecision.HUMAN_REVIEW


def may_publish(*, decision: str, review_status: str | None, is_leaf: bool = True) -> bool:
    """The only automatic publication transition allowed by P0-05."""

    return (
        decision == ReviewDecision.APPROVE.value
        and review_status == "approved"
        and is_leaf
    )


def locked_human_review_resource_ids(
    resources: Iterable[Any],
    executions: Iterable[dict[str, Any]],
) -> set[str]:
    """Return resources whose generation failure must remain fail-closed."""

    locked = {
        str(resource.resource_id)
        for resource in resources
        if getattr(resource, "review_status", None) == ReviewDecision.HUMAN_REVIEW.value
    }
    locked.update(
        str(item["resource_id"])
        for item in executions
        if isinstance(item, dict)
        and item.get("resource_id")
        and (
            item.get("resource_execution_state") == ReviewDecision.HUMAN_REVIEW.value
            or item.get("validation_status") == "failed"
        )
    )
    return locked


def target_resource_types(instructions: Iterable[dict[str, Any]]) -> set[str]:
    return {
        str(item["target_resource_type"])
        for item in instructions
        if isinstance(item, dict) and item.get("target_resource_type")
    }
