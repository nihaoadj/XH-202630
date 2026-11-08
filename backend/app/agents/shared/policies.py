"""Deterministic review and publication policies.

The reviewer model may recommend a decision, but it never owns the release gate.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from app.models.shared.workflow import ResourceStatus, ReviewDecision


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


class PublicationReason(str, Enum):
    """Controlled reason codes for the automatic terminal publication decision."""

    APPROVED = "approved"
    ORDINARY_REJECTED = "ordinary_rejected"
    ORDINARY_REVIEW_REQUIRED = "ordinary_review_required"
    ORDINARY_REVISION_UNRESOLVED = "ordinary_revision_unresolved"
    GENERATION_LOCKED = "generation_locked"
    CLAIM_GATE_FAILED = "claim_gate_failed"
    CLAIM_METRIC_INCOMPLETE = "claim_metric_incomplete"
    CLAIM_USER_REVIEW_REQUIRED = "claim_user_review_required"
    CLAIM_EVIDENCE_HARD_BLOCK = "claim_evidence_hard_block"
    CLAIM_EVIDENCE_IN_FLIGHT = "claim_evidence_in_flight"
    STRICT_DEGRADATION = "strict_degradation"


# Canonical resource state for one ordinary review decision.  ``revise`` means
# the revision budget is exhausted, so it resolves to human review rather than
# to an automatic publication.
_ORDINARY_STATUS_BY_DECISION: dict[str, ResourceStatus] = {
    "approve": ResourceStatus.APPROVED,
    "reject": ResourceStatus.REJECTED,
    "human_review": ResourceStatus.HUMAN_REVIEW,
    "revise": ResourceStatus.HUMAN_REVIEW,
}

_ORDINARY_REASON_BY_DECISION: dict[str, PublicationReason] = {
    "approve": PublicationReason.APPROVED,
    "reject": PublicationReason.ORDINARY_REJECTED,
    "human_review": PublicationReason.ORDINARY_REVIEW_REQUIRED,
    "revise": PublicationReason.ORDINARY_REVISION_UNRESOLVED,
}

_REASON_BY_FALLBACK_STATUS: dict[ResourceStatus, PublicationReason] = {
    ResourceStatus.APPROVED: PublicationReason.APPROVED,
    ResourceStatus.REJECTED: PublicationReason.ORDINARY_REJECTED,
    ResourceStatus.REVISION_REQUESTED: PublicationReason.ORDINARY_REVISION_UNRESOLVED,
}


@dataclass(frozen=True, slots=True)
class PublicationInputs:
    """Explicit inputs for one resource's terminal automatic decision.

    ``fallback_status`` is the run-level terminal status the caller already
    derived from the aggregate review decision; it only applies when the item
    carries no recognised per-resource decision.
    """

    item_decision: str
    fallback_status: ResourceStatus
    is_locked: bool
    strict_with_degradation: bool
    include_claim_check: bool
    is_claim_eligible: bool
    claim_failed: bool
    has_claim_problem: bool
    claim_metric_status: str | None
    factual_claim_total: int = 0
    supported_claim_total: int = 0
    contradicted_claim_total: int = 0
    not_in_evidence_claim_total: int = 0
    allow_partial_claim_publish: bool = False
    claim_user_review_enabled: bool = False
    claim_user_review_min_factual_pass_rate: float = 0.0
    # A persisted round-1 counter-evidence or source conflict permanently binds
    # this resource version.  It is checked before every other allowance.
    claim_hard_block: bool = False
    # An in-flight or interrupted claim-evidence round keeps this version
    # unpublished for now; the durable guard in the repositories is the final
    # authority and re-reads the same state before any publication write.
    claim_publication_barrier: bool = False


@dataclass(frozen=True, slots=True)
class PublicationDecision:
    """Terminal review/publication outcome for a single logical resource."""

    review_status: ResourceStatus
    publish: bool
    reason: PublicationReason
    claim_publish_decision_pending: bool
    claim_degraded_publish: bool
    factual_pass_rate: float | None


def resolve_publication(inputs: PublicationInputs) -> PublicationDecision:
    """Resolve one resource's terminal state from already-computed inputs.

    This is the only production automatic terminal-decision entry point.  It
    performs no IO, reads no global configuration and writes no event; the
    caller passes the configuration that applies to the execution it is
    finishing.  Condition priority mirrors the historical inline node logic.
    """

    factual_pass_rate = (
        inputs.supported_claim_total / inputs.factual_claim_total
        if inputs.factual_claim_total
        else None
    )
    claim_metric_complete = inputs.claim_metric_status == "complete"
    partial_metric_allowed = (
        inputs.allow_partial_claim_publish
        and inputs.is_claim_eligible
        and inputs.item_decision == ReviewDecision.APPROVE.value
        and inputs.claim_metric_status == "incomplete"
    )
    user_review_allowed = (
        inputs.claim_user_review_enabled
        and inputs.item_decision == ReviewDecision.APPROVE.value
        and inputs.is_claim_eligible
        and claim_metric_complete
        and factual_pass_rate is not None
        and factual_pass_rate >= inputs.claim_user_review_min_factual_pass_rate
        and inputs.contradicted_claim_total == 0
        and inputs.not_in_evidence_claim_total > 0
    )

    if inputs.claim_hard_block:
        review_status = ResourceStatus.HUMAN_REVIEW
        reason = PublicationReason.CLAIM_EVIDENCE_HARD_BLOCK
    elif inputs.claim_publication_barrier:
        review_status = ResourceStatus.HUMAN_REVIEW
        reason = PublicationReason.CLAIM_EVIDENCE_IN_FLIGHT
    elif inputs.is_locked:
        review_status = ResourceStatus.HUMAN_REVIEW
        reason = PublicationReason.GENERATION_LOCKED
    elif (
        inputs.has_claim_problem
        and not partial_metric_allowed
        and not user_review_allowed
    ):
        review_status = ResourceStatus.HUMAN_REVIEW
        reason = PublicationReason.CLAIM_GATE_FAILED
    elif user_review_allowed:
        review_status = ResourceStatus.HUMAN_REVIEW
        reason = PublicationReason.CLAIM_USER_REVIEW_REQUIRED
    else:
        review_status = _ORDINARY_STATUS_BY_DECISION.get(
            inputs.item_decision, inputs.fallback_status
        )
        reason = _ORDINARY_REASON_BY_DECISION.get(inputs.item_decision) or (
            PublicationReason.STRICT_DEGRADATION
            if inputs.strict_with_degradation
            else _REASON_BY_FALLBACK_STATUS.get(
                inputs.fallback_status, PublicationReason.ORDINARY_REVIEW_REQUIRED
            )
        )

    if inputs.include_claim_check and review_status == ResourceStatus.APPROVED:
        claim_gate_passed = (
            inputs.is_claim_eligible
            and not inputs.claim_failed
            and not inputs.has_claim_problem
            and inputs.claim_metric_status in {"complete", "not_applicable"}
        )
        if not claim_gate_passed and not partial_metric_allowed and not user_review_allowed:
            review_status = ResourceStatus.HUMAN_REVIEW
            reason = (
                PublicationReason.CLAIM_METRIC_INCOMPLETE
                if inputs.claim_metric_status == "incomplete"
                else PublicationReason.CLAIM_GATE_FAILED
            )

    publish = review_status == ResourceStatus.APPROVED
    return PublicationDecision(
        review_status=review_status,
        publish=publish,
        reason=reason,
        claim_publish_decision_pending=user_review_allowed,
        claim_degraded_publish=bool(
            publish
            and inputs.allow_partial_claim_publish
            and inputs.claim_metric_status == "incomplete"
        ),
        factual_pass_rate=factual_pass_rate,
    )


def may_publish(*, decision: str, review_status: str | None, is_leaf: bool = True) -> bool:
    """Legacy standalone predicate: final state plus leaf eligibility.

    Kept as an independent testing/compatibility contract for callers that
    supply a leaf-version eligibility flag; production automatic terminal
    decisions go through :func:`resolve_publication`, which has no leaf input.
    """

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
