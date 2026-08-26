from datetime import datetime, timedelta, timezone

import pytest

from app.db.audit.base import PersistenceConflict
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    RunStatus,
    WorkflowEventType,
)
from backend.tests.fakes.persistence import create_command, memory_repository, sqlite_repository


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        return memory_repository()
    return sqlite_repository(tmp_path)[0]


def test_repository_preserves_ids_sequences_and_terminal_state(repository):
    command = create_command()
    created = repository.create_run(command)
    assert created.started_at is None
    repository.create_run(command)
    assert len(repository.list_events(command.run_id)) == 1
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    step = BeginStepCommand(
        run_id=command.run_id,
        step_id="step-001",
        step_sequence=1,
        node_name="diagnose",
        agent_name="diagnosis",
        action="学情诊断",
        started_at=command.occurred_at,
    )
    repository.begin_step(step)
    completed = repository.complete_step(
        CompleteStepCommand(
            run_id=command.run_id,
            step_id=step.step_id,
            trace={
                "run_id": command.run_id,
                "step_id": step.step_id,
                "sequence": 1,
                "status": "success",
                "attempt": 1,
                "output_summary": "完成",
            },
            ended_at=command.occurred_at + timedelta(milliseconds=10),
        )
    )
    assert completed.step_id == "step-001"
    duplicate = repository.complete_step(
        CompleteStepCommand(
            run_id=command.run_id,
            step_id=step.step_id,
            trace={
                "run_id": command.run_id,
                "step_id": step.step_id,
                "sequence": 1,
                "status": "success",
                "attempt": 1,
                "output_summary": "完成",
            },
            ended_at=command.occurred_at + timedelta(milliseconds=10),
        )
    )
    assert duplicate.payload_hash == completed.payload_hash
    repository.mark_finalizing(
        command.run_id,
        workflow_status="completed",
        current_node="supervisor",
        generation_attempt=1,
        revision_count=0,
        retrieval_status="available",
        final_decision="通过",
        occurred_at=command.occurred_at,
    )
    run = repository.complete_run(
        command.run_id,
        status=RunStatus.COMPLETED,
        workflow_status="completed",
        execution_status="success",
        final_decision="通过",
        occurred_at=command.occurred_at,
    )
    assert run.run_id == command.run_id
    assert run.status == RunStatus.COMPLETED
    events = repository.list_events(command.run_id)
    assert [item.event_sequence for item in events] == list(range(1, len(events) + 1))
    with pytest.raises((ValueError, PersistenceConflict)):
        repository.start_run(command.run_id, occurred_at=datetime.now(timezone.utc))


def test_repository_rejects_non_monotonic_step_sequence(repository):
    command = create_command("run-sequence")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    with pytest.raises(PersistenceConflict):
        repository.begin_step(
            BeginStepCommand(
                run_id=command.run_id,
                step_id="step-002",
                step_sequence=2,
                node_name="retrieve",
                agent_name="retriever",
                action="检索",
            )
        )


def test_event_id_is_idempotent_only_for_the_same_payload(repository):
    command = create_command("run-event-idempotency")
    repository.create_run(command)
    repository.start_run(command.run_id, occurred_at=command.occurred_at)
    first = repository.append_event(
        command.run_id,
        WorkflowEventType.RESOURCE_PERSISTED,
        payload={"resource_ids": ["resource-001"]},
        occurred_at=command.occurred_at,
        event_id="event-stable",
    )
    duplicate = repository.append_event(
        command.run_id,
        WorkflowEventType.RESOURCE_PERSISTED,
        payload={"resource_ids": ["resource-001"]},
        occurred_at=command.occurred_at,
        event_id="event-stable",
    )
    assert duplicate.event_sequence == first.event_sequence
    with pytest.raises(PersistenceConflict):
        repository.append_event(
            command.run_id,
            WorkflowEventType.RESOURCE_PERSISTED,
            payload={"resource_ids": ["resource-002"]},
            occurred_at=command.occurred_at,
            event_id="event-stable",
        )


def test_expired_lease_is_interrupted_but_live_lease_is_not(repository):
    now = datetime.now(timezone.utc)
    expired = create_command("run-expired")
    live = create_command("run-live")
    repository.create_run(expired)
    repository.start_run("run-expired", occurred_at=now, lease_expires_at=now - timedelta(seconds=1))
    repository.create_run(live)
    repository.start_run("run-live", occurred_at=now, lease_expires_at=now + timedelta(minutes=1))
    assert repository.mark_stale_interrupted(before=now, occurred_at=now) == 1
    assert repository.get_run("run-expired").status == RunStatus.INTERRUPTED
    assert repository.get_run("run-live").status == RunStatus.RUNNING
