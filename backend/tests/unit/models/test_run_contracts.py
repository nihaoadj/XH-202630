from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.shared.persistence import (
    RunStatus,
    WorkflowEvent,
    WorkflowEventType,
    canonical_hash,
    require_run_transition,
)


def test_run_state_machine_accepts_only_declared_transitions():
    require_run_transition(RunStatus.CREATED, RunStatus.RUNNING)
    require_run_transition(RunStatus.RUNNING, RunStatus.FINALIZING)
    require_run_transition(RunStatus.FINALIZING, RunStatus.COMPLETED)
    with pytest.raises(ValueError):
        require_run_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
    with pytest.raises(ValueError):
        require_run_transition(RunStatus.CREATED, RunStatus.COMPLETED)


def test_canonical_hash_is_order_independent_and_unicode_safe():
    assert canonical_hash({"b": "中文", "a": 1}) == canonical_hash({"a": 1, "b": "中文"})


def test_event_contract_forbids_sensitive_payload_fields_and_extra_fields():
    common = {
        "event_id": "event-001",
        "run_id": "run-001",
        "event_sequence": 1,
        "event_type": WorkflowEventType.RUN_CREATED,
        "payload_hash": canonical_hash({}),
        "occurred_at": datetime.now(timezone.utc),
    }
    with pytest.raises(ValidationError):
        WorkflowEvent(**common, payload={"query": "raw retrieval query"})
    with pytest.raises(ValidationError):
        WorkflowEvent(**common, payload={}, unexpected=True)


def test_event_contract_accepts_nested_json_and_checks_sensitive_keys_recursively():
    common = {
        "event_id": "event-002",
        "run_id": "run-001",
        "event_sequence": 2,
        "event_type": WorkflowEventType.CLAIM_JUDGEMENT_COMPLETED,
        "occurred_at": datetime.now(timezone.utc),
    }
    payload = {"verdict_counts": {"supported": 2, "non_factual": 1}}
    event = WorkflowEvent(**common, payload=payload, payload_hash=canonical_hash(payload))
    assert event.payload == payload
    with pytest.raises(ValidationError):
        WorkflowEvent(**common, payload={"nested": [{"raw_response": "secret"}]}, payload_hash=canonical_hash({}))
