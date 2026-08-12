from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

from app.db.audit.base import (
    BaseAuditRepository,
    PersistenceConflict,
    RunNotFound,
)
from app.models.persistence import (
    AgentRunRecord,
    AgentStepRecord,
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    PersistedEvidenceSnapshot,
    ReplayCompleteness,
    RunStatus,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowEventType,
    canonical_hash,
    require_run_transition,
)
from app.models.schemas import ResourceClaim, ReviewSummary, SourceRef


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class MemoryAuditRepository(BaseAuditRepository):
    """Thread-safe lifecycle repository used by tests and DB_TYPE=memory."""

    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.reviews: dict[str, dict[str, Any]] = {}
        self.steps: dict[str, dict[str, AgentStepRecord]] = {}
        self.events: dict[str, list[WorkflowEvent]] = {}
        self.checkpoints: dict[str, list[WorkflowCheckpoint]] = {}
        self.evidence: dict[str, dict[str, PersistedEvidenceSnapshot]] = {}
        self._lock = threading.RLock()

    def _require_run(self, run_id: str) -> dict[str, Any]:
        run = self.runs.get(run_id)
        if run is None:
            raise RunNotFound("run not found")
        return run

    def _run_record(self, run: dict[str, Any]) -> AgentRunRecord:
        fields = AgentRunRecord.model_fields
        return AgentRunRecord.model_validate({key: run.get(key) for key in fields})

    def _append_event(
        self,
        run: dict[str, Any],
        event_type: WorkflowEventType,
        *,
        payload: dict[str, Any],
        occurred_at: datetime,
        step_id: str | None = None,
        step_sequence: int | None = None,
        node_name: str | None = None,
        status: str | None = None,
        error_code: str | None = None,
        event_id: str | None = None,
    ) -> WorkflowEvent:
        event_id = event_id or str(uuid.uuid4())
        existing = next(
            (
                item
                for events in self.events.values()
                for item in events
                if item.event_id == event_id
            ),
            None,
        )
        if existing is not None:
            if (
                existing.run_id == run["run_id"]
                and existing.event_type == event_type
                and existing.payload_hash == canonical_hash(payload)
                and existing.step_id == step_id
                and existing.status == status
                and existing.error_code == error_code
            ):
                return existing
            raise PersistenceConflict("event id conflicts with durable state")
        sequence = int(run["last_event_sequence"]) + 1
        event = WorkflowEvent(
            event_id=event_id,
            run_id=run["run_id"],
            event_sequence=sequence,
            event_type=event_type,
            step_id=step_id,
            step_sequence=step_sequence,
            node_name=node_name,
            status=status,
            payload=payload,
            payload_hash=canonical_hash(payload),
            error_code=error_code,
            occurred_at=occurred_at,
            persisted_at=_utcnow(),
        )
        self.events[run["run_id"]].append(event)
        run["last_event_sequence"] = sequence
        run["updated_at"] = _utcnow()
        run["row_version"] += 1
        return event

    def create_run(self, command: CreateRunCommand) -> AgentRunRecord:
        with self._lock:
            existing = self.runs.get(command.run_id)
            if existing is not None:
                if existing["request_hash"] != command.request_hash:
                    raise PersistenceConflict("run id conflicts with another request")
                return self._run_record(existing)
            now = command.occurred_at
            run = {
                "schema_version": "1.0",
                "run_id": command.run_id,
                "learner_id": command.learner_id,
                "knowledge_base_id": command.knowledge_base_id,
                "topic": command.topic,
                "request_hash": command.request_hash,
                "status": RunStatus.CREATED.value,
                "workflow_status": None,
                "execution_status": None,
                "current_node": "pending",
                "current_step_id": None,
                "current_step_sequence": 0,
                "last_event_sequence": 0,
                "generation_attempt": 1,
                "revision_count": 0,
                "retrieval_status": "pending",
                "final_decision": None,
                "last_error_code": None,
                "replay_completeness": ReplayCompleteness.COMPLETE.value,
                "owner_instance_id": command.owner_instance_id,
                "lease_expires_at": command.lease_expires_at,
                "heartbeat_at": None,
                "started_at": None,
                "updated_at": now,
                "ended_at": None,
                "row_version": 1,
                # Compatibility views used by existing tests and review tooling.
                "trace": [],
                "input_payload": command.request_snapshot,
                "output_payload": {},
            }
            self.runs[command.run_id] = run
            self.steps[command.run_id] = {}
            self.events[command.run_id] = []
            self.checkpoints[command.run_id] = []
            self.evidence[command.run_id] = {}
            self._append_event(
                run,
                WorkflowEventType.RUN_CREATED,
                payload={"request_hash": command.request_hash},
                occurred_at=now,
                status=RunStatus.CREATED.value,
            )
            return self._run_record(run)

    def start_run(
        self,
        run_id: str,
        *,
        occurred_at: datetime,
        lease_expires_at: datetime | None = None,
    ) -> AgentRunRecord:
        with self._lock:
            run = self._require_run(run_id)
            if run["status"] == RunStatus.RUNNING.value:
                return self._run_record(run)
            require_run_transition(run["status"], RunStatus.RUNNING)
            run["status"] = RunStatus.RUNNING.value
            run["workflow_status"] = "running"
            run["execution_status"] = "running"
            run["started_at"] = occurred_at
            run["heartbeat_at"] = occurred_at
            run["lease_expires_at"] = lease_expires_at
            self._append_event(
                run,
                WorkflowEventType.RUN_STARTED,
                payload={},
                occurred_at=occurred_at,
                status=RunStatus.RUNNING.value,
            )
            return self._run_record(run)

    def begin_step(self, command: BeginStepCommand) -> AgentStepRecord:
        with self._lock:
            run = self._require_run(command.run_id)
            if run["status"] != RunStatus.RUNNING.value:
                raise PersistenceConflict("step can only begin while run is running")
            existing = self.steps[command.run_id].get(command.step_id)
            if existing is not None:
                if (
                    existing.step_sequence == command.step_sequence
                    and existing.node_name == command.node_name
                ):
                    return existing
                raise PersistenceConflict("step id conflicts with durable state")
            if command.step_sequence != run["current_step_sequence"] + 1:
                raise PersistenceConflict("step sequence is not monotonic")
            record = AgentStepRecord(
                step_id=command.step_id,
                run_id=command.run_id,
                step_sequence=command.step_sequence,
                agent_name=command.agent_name,
                node_name=command.node_name,
                action=command.action,
                status="running",
                generation_attempt=command.generation_attempt,
                started_at=command.started_at,
            )
            self.steps[command.run_id][command.step_id] = record
            run["current_step_id"] = command.step_id
            run["current_step_sequence"] = command.step_sequence
            run["current_node"] = command.node_name
            run["generation_attempt"] = command.generation_attempt
            run["heartbeat_at"] = command.started_at
            if command.lease_expires_at is not None:
                run["lease_expires_at"] = command.lease_expires_at
            self._append_event(
                run,
                WorkflowEventType.STEP_STARTED,
                payload={"attempt": command.generation_attempt},
                occurred_at=command.started_at,
                step_id=command.step_id,
                step_sequence=command.step_sequence,
                node_name=command.node_name,
                status="running",
            )
            return record

    def complete_step(self, command: CompleteStepCommand) -> AgentStepRecord:
        with self._lock:
            run = self._require_run(command.run_id)
            current = self.steps[command.run_id].get(command.step_id)
            if current is None:
                raise RunNotFound("step not found")
            trace = dict(command.trace)
            if trace.get("run_id") not in {None, command.run_id}:
                raise PersistenceConflict("trace run id mismatch")
            if trace.get("step_id") not in {None, command.step_id}:
                raise PersistenceConflict("trace step id mismatch")
            payload = {
                key: trace.get(key)
                for key in (
                    "status",
                    "attempt",
                    "input_summary",
                    "output_summary",
                    "decision_reason",
                    "evidence_refs",
                    "resource_ids",
                    "review_ids",
                    "retry_count",
                    "error_code",
                    "llm_call_id",
                    "model_name",
                    "provider_request_id",
                    "structured_output_mode",
                    "finish_reason",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "llm_duration_ms",
                    "llm_attempts",
                    "retrieval_status",
                    "retrieval_config_hash",
                    "retrieval_query_hashes",
                    "retrieval_candidate_count",
                    "retrieval_dropped_candidate_count",
                    "retrieval_partial_failure_count",
                    "retrieval_profile",
                    "workflow_elapsed_ms",
                    "workflow_remaining_ms",
                )
                if trace.get(key) is not None
            }
            payload_hash = canonical_hash(payload)
            if current.status != "running":
                if current.payload_hash == payload_hash:
                    return current
                raise PersistenceConflict("terminal step cannot be changed")
            for snapshot in command.evidence:
                if snapshot.run_id != command.run_id or snapshot.retrieval_step_id != command.step_id:
                    raise PersistenceConflict("evidence is outside the current run/step")
                if run["knowledge_base_id"] and snapshot.knowledge_base_id != run["knowledge_base_id"]:
                    raise PersistenceConflict("evidence is outside the current knowledge base")
                existing = self.evidence[command.run_id].get(snapshot.evidence_id)
                if existing is not None and existing.snapshot_hash != snapshot.snapshot_hash:
                    raise PersistenceConflict("evidence snapshot is immutable")
            record = AgentStepRecord(
                **current.model_dump(exclude={
                    "status",
                    "generation_attempt",
                    "input_summary",
                    "output_summary",
                    "decision_reason",
                    "evidence_refs",
                    "resource_ids",
                    "review_ids",
                    "retry_count",
                    "error_code",
                    "error_message",
                    "llm_call_id",
                    "model_name",
                    "provider_request_id",
                    "structured_output_mode",
                    "finish_reason",
                    "input_tokens",
                    "output_tokens",
                    "total_tokens",
                    "llm_duration_ms",
                    "llm_attempts",
                    "retrieval_status",
                    "retrieval_config_hash",
                    "retrieval_query_hashes",
                    "retrieval_candidate_count",
                    "retrieval_dropped_candidate_count",
                    "retrieval_partial_failure_count",
                    "retrieval_profile",
                    "workflow_elapsed_ms",
                    "workflow_remaining_ms",
                    "payload_hash",
                    "ended_at",
                    "duration_ms",
                }),
                status=str(trace.get("status") or "failed"),
                generation_attempt=int(trace.get("attempt") or current.generation_attempt),
                input_summary=trace.get("input_summary"),
                output_summary=trace.get("output_summary"),
                decision_reason=trace.get("decision_reason"),
                evidence_refs=list(trace.get("evidence_refs") or []),
                resource_ids=list(trace.get("resource_ids") or []),
                review_ids=list(trace.get("review_ids") or []),
                retry_count=int(trace.get("retry_count") or 0),
                error_code=trace.get("error_code"),
                error_message=trace.get("error_message"),
                llm_call_id=trace.get("llm_call_id"),
                model_name=trace.get("model_name"),
                provider_request_id=trace.get("provider_request_id"),
                structured_output_mode=trace.get("structured_output_mode"),
                finish_reason=trace.get("finish_reason"),
                input_tokens=trace.get("input_tokens"),
                output_tokens=trace.get("output_tokens"),
                total_tokens=trace.get("total_tokens"),
                llm_duration_ms=trace.get("llm_duration_ms"),
                llm_attempts=trace.get("llm_attempts") or [],
                retrieval_status=trace.get("retrieval_status"),
                retrieval_config_hash=trace.get("retrieval_config_hash"),
                retrieval_query_hashes=trace.get("retrieval_query_hashes") or [],
                retrieval_candidate_count=trace.get("retrieval_candidate_count"),
                retrieval_dropped_candidate_count=trace.get("retrieval_dropped_candidate_count"),
                retrieval_partial_failure_count=trace.get("retrieval_partial_failure_count"),
                retrieval_profile=trace.get("retrieval_profile") or {},
                workflow_elapsed_ms=trace.get("workflow_elapsed_ms"),
                workflow_remaining_ms=trace.get("workflow_remaining_ms"),
                payload_hash=payload_hash,
                ended_at=command.ended_at,
                duration_ms=max(
                    0,
                    int((command.ended_at - current.started_at).total_seconds() * 1000),
                ),
            )
            self.steps[command.run_id][command.step_id] = record
            run["trace"].append(trace)
            run["generation_attempt"] = record.generation_attempt
            run["retrieval_status"] = record.retrieval_status or run["retrieval_status"]
            run["last_error_code"] = record.error_code
            terminal_event = (
                WorkflowEventType.STEP_DEGRADED
                if record.status == "degraded"
                else WorkflowEventType.STEP_FAILED
                if record.status in {"failed", "retryable_error"}
                else WorkflowEventType.STEP_SUCCEEDED
            )
            self._append_event(
                run,
                terminal_event,
                payload={
                    "attempt": record.generation_attempt,
                    "retry_count": record.retry_count,
                    "evidence_ids": record.evidence_refs,
                    "resource_ids": record.resource_ids,
                    "review_ids": record.review_ids,
                    "duration_ms": record.duration_ms,
                    "candidate_count": record.retrieval_candidate_count,
                    "dropped_count": record.retrieval_dropped_candidate_count,
                    "valid_evidence_count": len(record.evidence_refs),
                },
                occurred_at=command.ended_at,
                step_id=record.step_id,
                step_sequence=record.step_sequence,
                node_name=record.node_name,
                status=record.status,
                error_code=record.error_code,
            )
            saved_ids: list[str] = []
            for snapshot in command.evidence:
                existing = self.evidence[command.run_id].get(snapshot.evidence_id)
                self.evidence[command.run_id][snapshot.evidence_id] = snapshot
                if existing is None:
                    saved_ids.append(snapshot.evidence_id)
            if saved_ids:
                self._append_event(
                    run,
                    WorkflowEventType.EVIDENCE_SNAPSHOT_SAVED,
                    payload={"evidence_ids": saved_ids, "count": len(saved_ids)},
                    occurred_at=command.ended_at,
                    step_id=record.step_id,
                    step_sequence=record.step_sequence,
                    node_name=record.node_name,
                    status=record.status,
                )
            return record

    def save_checkpoint(
        self,
        *,
        run_id: str,
        step_id: str,
        step_sequence: int,
        node_name: str,
        state_projection: dict[str, Any],
        state_hash: str,
        occurred_at: datetime,
    ) -> WorkflowCheckpoint:
        with self._lock:
            run = self._require_run(run_id)
            if canonical_hash(state_projection) != state_hash:
                raise PersistenceConflict("checkpoint hash mismatch")
            existing = next(
                (
                    item
                    for item in self.checkpoints[run_id]
                    if item.step_id == step_id
                ),
                None,
            )
            if existing is not None:
                if existing.state_hash == state_hash:
                    return existing
                raise PersistenceConflict("checkpoint for step is immutable")
            event = self._append_event(
                run,
                WorkflowEventType.CHECKPOINT_SAVED,
                payload={"state_hash": state_hash},
                occurred_at=occurred_at,
                step_id=step_id,
                step_sequence=step_sequence,
                node_name=node_name,
                status="saved",
            )
            checkpoint = WorkflowCheckpoint(
                checkpoint_id=str(uuid.uuid4()),
                run_id=run_id,
                event_sequence=event.event_sequence,
                step_id=step_id,
                step_sequence=step_sequence,
                node_name=node_name,
                state_projection=state_projection,
                state_hash=state_hash,
                created_at=occurred_at,
            )
            self.checkpoints[run_id].append(checkpoint)
            return checkpoint

    def mark_finalizing(
        self,
        run_id: str,
        *,
        workflow_status: str,
        current_node: str | None,
        generation_attempt: int,
        revision_count: int,
        retrieval_status: str | None,
        final_decision: str | None,
        occurred_at: datetime,
    ) -> AgentRunRecord:
        with self._lock:
            run = self._require_run(run_id)
            if run["status"] == RunStatus.FINALIZING.value:
                return self._run_record(run)
            require_run_transition(run["status"], RunStatus.FINALIZING)
            run.update(
                status=RunStatus.FINALIZING.value,
                workflow_status=workflow_status,
                execution_status="finalizing",
                current_node=current_node,
                generation_attempt=generation_attempt,
                revision_count=revision_count,
                retrieval_status=retrieval_status,
                final_decision=final_decision,
                heartbeat_at=occurred_at,
            )
            self._append_event(
                run,
                WorkflowEventType.RUN_FINALIZING,
                payload={"workflow_status": workflow_status},
                occurred_at=occurred_at,
                status=RunStatus.FINALIZING.value,
            )
            return self._run_record(run)

    def complete_run(
        self,
        run_id: str,
        *,
        status: RunStatus,
        workflow_status: str,
        execution_status: str,
        final_decision: str | None,
        occurred_at: datetime,
    ) -> AgentRunRecord:
        with self._lock:
            run = self._require_run(run_id)
            if run["status"] == status.value:
                return self._run_record(run)
            require_run_transition(run["status"], status)
            run.update(
                status=status.value,
                workflow_status=workflow_status,
                execution_status=execution_status,
                final_decision=final_decision,
                ended_at=occurred_at,
                heartbeat_at=occurred_at,
                lease_expires_at=None,
                output_payload={
                    "workflow_status": workflow_status,
                    "final_decision": final_decision,
                },
            )
            self._append_event(
                run,
                WorkflowEventType.RUN_FAILED if status == RunStatus.FAILED else WorkflowEventType.RUN_COMPLETED,
                payload={"workflow_status": workflow_status},
                occurred_at=occurred_at,
                status=status.value,
                error_code=(run.get("last_error_code") if status == RunStatus.FAILED else None),
            )
            return self._run_record(run)

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        occurred_at: datetime,
    ) -> AgentRunRecord:
        with self._lock:
            run = self._require_run(run_id)
            if run["status"] == RunStatus.FAILED.value:
                return self._run_record(run)
            require_run_transition(run["status"], RunStatus.FAILED)
            run.update(
                status=RunStatus.FAILED.value,
                workflow_status="failed",
                execution_status="failed",
                last_error_code=error_code,
                ended_at=occurred_at,
                heartbeat_at=occurred_at,
                lease_expires_at=None,
            )
            self._append_event(
                run,
                WorkflowEventType.RUN_FAILED,
                payload={},
                occurred_at=occurred_at,
                status=RunStatus.FAILED.value,
                error_code=error_code,
            )
            return self._run_record(run)

    def append_event(
        self,
        run_id: str,
        event_type: WorkflowEventType,
        *,
        payload: dict[str, Any],
        occurred_at: datetime,
        step_id: str | None = None,
        step_sequence: int | None = None,
        node_name: str | None = None,
        status: str | None = None,
        error_code: str | None = None,
        event_id: str | None = None,
    ) -> WorkflowEvent:
        with self._lock:
            return self._append_event(
                self._require_run(run_id),
                event_type,
                payload=payload,
                occurred_at=occurred_at,
                step_id=step_id,
                step_sequence=step_sequence,
                node_name=node_name,
                status=status,
                error_code=error_code,
                event_id=event_id,
            )

    def get_run(self, run_id: str) -> AgentRunRecord | None:
        with self._lock:
            run = self.runs.get(run_id)
            return self._run_record(run) if run else None

    def list_steps(self, run_id: str) -> list[AgentStepRecord]:
        with self._lock:
            return sorted(
                self.steps.get(run_id, {}).values(),
                key=lambda item: item.step_sequence,
            )

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkflowEvent]:
        with self._lock:
            return [
                item
                for item in self.events.get(run_id, [])
                if item.event_sequence > after_sequence
            ][:limit]

    def list_checkpoints(self, run_id: str) -> list[WorkflowCheckpoint]:
        with self._lock:
            return list(self.checkpoints.get(run_id, []))

    def list_evidence(self, run_id: str) -> list[PersistedEvidenceSnapshot]:
        with self._lock:
            return sorted(
                self.evidence.get(run_id, {}).values(),
                key=lambda item: (item.rank, item.evidence_id),
            )

    def mark_stale_interrupted(self, *, before: datetime, occurred_at: datetime) -> int:
        count = 0
        with self._lock:
            for run in self.runs.values():
                lease = run.get("lease_expires_at")
                if run["status"] not in {RunStatus.RUNNING.value, RunStatus.FINALIZING.value}:
                    continue
                if lease is None or lease >= before:
                    continue
                require_run_transition(run["status"], RunStatus.INTERRUPTED)
                run.update(
                    status=RunStatus.INTERRUPTED.value,
                    execution_status="interrupted",
                    ended_at=occurred_at,
                    last_error_code="WORKFLOW_RUN_INTERRUPTED",
                    lease_expires_at=None,
                )
                self._append_event(
                    run,
                    WorkflowEventType.RUN_INTERRUPTED,
                    payload={},
                    occurred_at=occurred_at,
                    status=RunStatus.INTERRUPTED.value,
                    error_code="WORKFLOW_RUN_INTERRUPTED",
                )
                count += 1
        return count

    def save_run(
        self,
        learner_id,
        knowledge_base_id,
        topic,
        trace: Iterable[dict[str, Any]],
        input_payload,
        output_payload,
        status,
        run_id=None,
    ):
        """Legacy adapter. New generation code must use lifecycle methods."""

        if not run_id:
            raise ValueError("run_id must be preallocated")
        now = _utcnow()
        command = CreateRunCommand(
            run_id=run_id,
            learner_id=learner_id,
            knowledge_base_id=knowledge_base_id,
            topic=topic,
            request_snapshot=input_payload,
            request_hash=canonical_hash(input_payload),
            occurred_at=now,
        )
        self.create_run(command)
        self.start_run(run_id, occurred_at=now)
        for sequence, raw_trace in enumerate(trace, start=1):
            item = dict(raw_trace)
            step_id = item.get("step_id") or f"{run_id}:{sequence}"
            item.update(run_id=run_id, step_id=step_id, sequence=sequence)
            self.begin_step(
                BeginStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    step_sequence=sequence,
                    node_name=item.get("node_name") or item.get("agent_name", "unknown"),
                    agent_name=item.get("agent_name", "unknown"),
                    action=item.get("action", "unknown"),
                    generation_attempt=item.get("attempt", 1),
                    started_at=now,
                )
            )
            self.complete_step(
                CompleteStepCommand(run_id=run_id, step_id=step_id, trace=item, ended_at=now)
            )
        normalized = RunStatus(status)
        if normalized == RunStatus.FAILED:
            self.fail_run(run_id, error_code="WORKFLOW_FAILED", occurred_at=now)
        else:
            self.mark_finalizing(
                run_id,
                workflow_status=status,
                current_node=None,
                generation_attempt=1,
                revision_count=0,
                retrieval_status=None,
                final_decision=output_payload.get("final_decision"),
                occurred_at=now,
            )
            self.complete_run(
                run_id,
                status=normalized,
                workflow_status=status,
                execution_status="success" if normalized == RunStatus.COMPLETED else status,
                final_decision=output_payload.get("final_decision"),
                occurred_at=now,
            )
        return run_id

    def save_review(self, resource_id: str, review: dict[str, Any], run_id: Optional[str]) -> str:
        review_id = review.get("review_ids", {}).get(resource_id) or review.get("review_id") or str(uuid.uuid4())
        payload = {"resource_id": resource_id, "run_id": run_id, **review}
        review_hash = canonical_hash(payload)
        existing = self.reviews.get(review_id)
        if existing is not None:
            if existing.get("review_hash") != review_hash:
                raise PersistenceConflict("review payload conflict")
            return review_id
        self.reviews[review_id] = {
            "review_id": review_id,
            **payload,
            "review_hash": review_hash,
        }
        return review_id

    def list_reviews_by_run(self, run_id: str) -> list[dict[str, Any]]:
        return [
            dict(review)
            for _, review in sorted(self.reviews.items())
            if review.get("run_id") == run_id
        ]

    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        for review_id, review in reversed(list(self.reviews.items())):
            if review["resource_id"] != resource_id:
                continue
            claims = [
                ResourceClaim(
                    claim_id=str(claim.get("claim_id", "")),
                    text=claim.get("text") or claim.get("claim_text", ""),
                    knowledge_point=claim.get("knowledge_point"),
                    supported=bool(claim.get("supported", False)),
                    confidence=claim.get("confidence"),
                    evidence_refs=[
                        SourceRef(
                            doc_id=ref.get("doc_id", "unknown"),
                            title=ref.get("title", ref.get("doc_id", "未知来源")),
                            snippet=ref.get("snippet", ""),
                            score=float(ref.get("score", 0.0)),
                            chunk_id=ref.get("chunk_id"),
                            source_path=ref.get("source_path"),
                            metadata=ref,
                        )
                        for ref in claim.get("evidence_refs", [])
                    ],
                    issue_type=claim.get("issue_type"),
                    correction=claim.get("correction"),
                    review_comment=claim.get("review_comment"),
                )
                for claim in review.get("claims", [])
            ]
            status = review.get("status") or ("passed" if review.get("passed") else "needs_review")
            return ReviewSummary(
                review_id=review_id,
                resource_id=resource_id,
                status=status,
                claim_total=review.get("claim_total", len(claims)),
                claim_supported=review.get("claim_supported", sum(claim.supported for claim in claims)),
                claim_unsupported=review.get("claim_unsupported", sum(not claim.supported for claim in claims)),
                suspected_hallucinations=review.get("suspected_hallucinations", sum(not claim.supported for claim in claims)),
                hallucination_rate=review.get("hallucination_rate", review.get("hallucination_score", 0.0)),
                legacy_reviewer_score=review.get("hallucination_score"),
                claim_hallucination_rate=review.get("claim_hallucination_rate"),
                claim_metric_status=review.get("claim_metric_status"),
                review_pass_rate=review.get(
                    "review_pass_rate",
                    1.0 if review.get("passed") or status in {"approve", "approved", "passed"} else 0.0,
                ),
                revision_count=review.get("revision_count", 0),
                issues=review.get("issues", []),
                revision_instructions=review.get("revision_instructions", []),
                claims=claims,
            )
        return None
