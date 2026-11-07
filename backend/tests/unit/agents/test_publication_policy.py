"""Direct unit coverage for the automatic publication resolver."""

from __future__ import annotations

import dataclasses

import pytest

from app.agents.shared.policies import (
    PublicationDecision,
    PublicationInputs,
    PublicationReason,
    resolve_publication,
)
from app.models.shared.workflow import ResourceStatus


def _inputs(**overrides) -> PublicationInputs:
    payload = {
        "item_decision": "approve",
        "fallback_status": ResourceStatus.APPROVED,
        "is_locked": False,
        "strict_with_degradation": False,
        "include_claim_check": False,
        "is_claim_eligible": False,
        "claim_failed": False,
        "has_claim_problem": False,
        "claim_metric_status": None,
        "factual_claim_total": 0,
        "supported_claim_total": 0,
        "contradicted_claim_total": 0,
        "not_in_evidence_claim_total": 0,
        "allow_partial_claim_publish": False,
        "claim_user_review_enabled": True,
        "claim_user_review_min_factual_pass_rate": 0.60,
    }
    payload.update(overrides)
    return PublicationInputs(**payload)


def _claim_metric(status="complete", factual=5, supported=5, contradicted=0, not_in_evidence=0):
    return {
        "include_claim_check": True,
        "is_claim_eligible": True,
        "claim_metric_status": status,
        "factual_claim_total": factual,
        "supported_claim_total": supported,
        "contradicted_claim_total": contradicted,
        "not_in_evidence_claim_total": not_in_evidence,
    }


@pytest.mark.parametrize(
    ("item_decision", "expected_status", "expected_reason"),
    [
        ("approve", ResourceStatus.APPROVED, PublicationReason.APPROVED),
        ("reject", ResourceStatus.REJECTED, PublicationReason.ORDINARY_REJECTED),
        ("human_review", ResourceStatus.HUMAN_REVIEW, PublicationReason.ORDINARY_REVIEW_REQUIRED),
        ("revise", ResourceStatus.HUMAN_REVIEW, PublicationReason.ORDINARY_REVISION_UNRESOLVED),
    ],
)
def test_ordinary_decisions_map_to_terminal_state(item_decision, expected_status, expected_reason):
    decision = resolve_publication(_inputs(item_decision=item_decision))
    assert decision.review_status is expected_status
    assert decision.publish is (expected_status is ResourceStatus.APPROVED)
    assert decision.reason is expected_reason
    assert decision.claim_publish_decision_pending is False
    assert decision.claim_degraded_publish is False
    assert decision.factual_pass_rate is None


def test_unrecognised_item_decision_falls_back_to_caller_status():
    decision = resolve_publication(
        _inputs(item_decision="not_requested", fallback_status=ResourceStatus.REJECTED)
    )
    assert decision.review_status is ResourceStatus.REJECTED
    assert decision.publish is False
    assert decision.reason is PublicationReason.ORDINARY_REJECTED


def test_strict_degradation_reason_only_when_it_is_the_effective_path():
    blocked = resolve_publication(_inputs(
        item_decision="not_requested",
        fallback_status=ResourceStatus.HUMAN_REVIEW,
        strict_with_degradation=True,
    ))
    assert blocked.review_status is ResourceStatus.HUMAN_REVIEW
    assert blocked.reason is PublicationReason.STRICT_DEGRADATION

    overridden = resolve_publication(_inputs(item_decision="approve", strict_with_degradation=True))
    assert overridden.publish is True
    assert overridden.reason is PublicationReason.APPROVED


def test_locked_resource_stays_in_human_review():
    decision = resolve_publication(_inputs(is_locked=True))
    assert decision.review_status is ResourceStatus.HUMAN_REVIEW
    assert decision.publish is False
    assert decision.reason is PublicationReason.GENERATION_LOCKED


def test_claim_gate_distinguishes_disabled_from_failed():
    disabled = resolve_publication(_inputs(**{**_claim_metric(), "include_claim_check": False}))
    assert disabled.publish is True

    not_eligible = resolve_publication(_inputs(**{**_claim_metric(), "is_claim_eligible": False}))
    assert not_eligible.review_status is ResourceStatus.HUMAN_REVIEW
    assert not_eligible.reason is PublicationReason.CLAIM_GATE_FAILED

    failed = resolve_publication(_inputs(**{**_claim_metric(), "claim_failed": True}))
    assert failed.review_status is ResourceStatus.HUMAN_REVIEW
    assert failed.reason is PublicationReason.CLAIM_GATE_FAILED


def test_claim_metric_incomplete_is_named_and_blocks_without_partial_switch():
    inputs = _inputs(**_claim_metric(status="incomplete", factual=0, supported=0))
    assert inputs.claim_metric_status == "incomplete"
    decision = resolve_publication(inputs)
    assert decision.review_status is ResourceStatus.HUMAN_REVIEW
    assert decision.reason is PublicationReason.CLAIM_METRIC_INCOMPLETE
    assert decision.factual_pass_rate is None


def test_partial_claim_publish_publishes_with_degradation_flag():
    decision = resolve_publication(
        _inputs(**_claim_metric(status="incomplete", factual=0, supported=0),
                allow_partial_claim_publish=True)
    )
    assert decision.review_status is ResourceStatus.APPROVED
    assert decision.publish is True
    assert decision.claim_degraded_publish is True
    assert decision.reason is PublicationReason.APPROVED


def test_claim_problem_blocks_unless_partial_publish_is_allowed():
    blocked = resolve_publication(_inputs(**_claim_metric(), has_claim_problem=True))
    assert blocked.review_status is ResourceStatus.HUMAN_REVIEW
    assert blocked.reason is PublicationReason.CLAIM_GATE_FAILED

    allowed = resolve_publication(_inputs(
        **_claim_metric(status="incomplete"),
        has_claim_problem=True,
        allow_partial_claim_publish=True,
    ))
    assert allowed.publish is True
    assert allowed.claim_degraded_publish is True


def test_not_applicable_and_zero_denominator_still_pass_the_gate():
    not_applicable = resolve_publication(
        _inputs(**_claim_metric(status="not_applicable", factual=0, supported=0))
    )
    assert not_applicable.publish is True
    assert not_applicable.factual_pass_rate is None

    zero_denominator = resolve_publication(
        _inputs(**_claim_metric(status="complete", factual=0, supported=0))
    )
    assert zero_denominator.publish is True
    assert zero_denominator.factual_pass_rate is None


def test_user_review_threshold_boundary_pends_publication():
    at_threshold = resolve_publication(
        _inputs(**_claim_metric(factual=5, supported=3, not_in_evidence=2))
    )
    assert at_threshold.factual_pass_rate == pytest.approx(0.6)
    assert at_threshold.review_status is ResourceStatus.HUMAN_REVIEW
    assert at_threshold.claim_publish_decision_pending is True
    assert at_threshold.reason is PublicationReason.CLAIM_USER_REVIEW_REQUIRED

    below = resolve_publication(
        _inputs(**_claim_metric(factual=5, supported=2, not_in_evidence=3))
    )
    assert below.publish is True
    assert below.claim_publish_decision_pending is False


def test_contradicted_claim_never_requests_user_review():
    decision = resolve_publication(
        _inputs(**_claim_metric(factual=5, supported=4, contradicted=1))
    )
    assert decision.claim_publish_decision_pending is False
    assert decision.publish is True


def test_user_review_switch_off_keeps_automatic_publication():
    decision = resolve_publication(_inputs(
        **_claim_metric(factual=5, supported=3, not_in_evidence=2),
        claim_user_review_enabled=False,
    ))
    assert decision.publish is True
    assert decision.claim_publish_decision_pending is False
    assert decision.reason is PublicationReason.APPROVED


def test_inputs_are_immutable_and_calls_are_repeatable():
    inputs = _inputs(**_claim_metric(factual=5, supported=3, not_in_evidence=2))
    assert dataclasses.is_dataclass(inputs)
    with pytest.raises(dataclasses.FrozenInstanceError):
        inputs.is_locked = True  # type: ignore[misc]
    first = resolve_publication(inputs)
    second = resolve_publication(inputs)
    assert first == second
    assert isinstance(first, PublicationDecision)
    assert first.reason is PublicationReason.CLAIM_USER_REVIEW_REQUIRED
