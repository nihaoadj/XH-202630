"""Deadline allocation guards for per-resource Claim auditing and assessment."""

from datetime import datetime, timedelta, timezone

from app.agents.resource_workflows.learning_documents.claim_review_agent import (
    _resource_deadline,
)

NOW = datetime(2026, 11, 3, 8, 0, 0, tzinfo=timezone.utc)


def test_resource_deadline_splits_the_remaining_budget_evenly():
    deadline = NOW + timedelta(seconds=900)

    first = _resource_deadline(deadline, resources_left=3, now=NOW)
    second = _resource_deadline(deadline, resources_left=2, now=NOW)
    last = _resource_deadline(deadline, resources_left=1, now=NOW)

    assert first == NOW + timedelta(seconds=300)
    assert second == NOW + timedelta(seconds=450)
    assert last == deadline


def test_resource_deadline_never_extends_the_workflow_deadline():
    deadline = NOW + timedelta(seconds=60)

    assert _resource_deadline(deadline, resources_left=5, now=NOW) <= deadline


def test_resource_deadline_returns_the_deadline_when_already_expired():
    expired = NOW - timedelta(seconds=5)

    assert _resource_deadline(expired, resources_left=3, now=NOW) == expired


def test_resource_deadline_passes_through_a_missing_deadline():
    assert _resource_deadline(None, resources_left=3, now=NOW) is None


def test_resource_deadline_keeps_a_single_resource_equal_to_the_full_budget():
    deadline = NOW + timedelta(seconds=900)

    assert _resource_deadline(deadline, resources_left=1, now=NOW) == deadline
