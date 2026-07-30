"""SQLAlchemy implementation of durable Agent lifecycle and review persistence."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.audit.base import (
    BaseAuditRepository,
    PersistenceConflict,
    RunNotFound,
)
from app.db.models import (
    AgentRunORM,
    AgentStepORM,
    ResourceClaimORM,
    ResourceReviewORM,
    RetrievalEvidenceSnapshotORM,
    WorkflowCheckpointORM,
    WorkflowEventORM,
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
from app.models.knowledge import SourceLocator, SourceType
from app.models.schemas import ResourceClaim, ReviewSummary, SourceRef


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


class SQLAuditRepository(BaseAuditRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def _run_record(self, orm: AgentRunORM) -> AgentRunRecord:
        return AgentRunRecord(
            schema_version=orm.schema_version or "1.0",
            run_id=orm.run_id,
            learner_id=orm.learner_id,
            knowledge_base_id=orm.knowledge_base_id,
            topic=orm.topic,
            request_hash=orm.request_hash or ("0" * 64),
            status=RunStatus(orm.status),
            workflow_status=orm.workflow_status,
            execution_status=orm.execution_status,
            current_node=orm.current_node,
            current_step_id=orm.current_step_id,
            current_step_sequence=orm.current_step_sequence or 0,
            last_event_sequence=orm.last_event_sequence or 0,
            generation_attempt=orm.generation_attempt or 1,
            revision_count=orm.revision_count or 0,
            retrieval_status=orm.retrieval_status,
            final_decision=orm.final_decision,
            last_error_code=orm.last_error_code,
            replay_completeness=(
                ReplayCompleteness.LEGACY_PARTIAL
                if not orm.request_hash
                else ReplayCompleteness(orm.replay_completeness or "complete")
            ),
            owner_instance_id=orm.owner_instance_id,
            lease_expires_at=_as_utc(orm.lease_expires_at),
            heartbeat_at=_as_utc(orm.heartbeat_at),
            started_at=_as_utc(orm.started_at),
            updated_at=_as_utc(orm.updated_at) or _utcnow(),
            ended_at=_as_utc(orm.ended_at),
            row_version=orm.row_version or 1,
        )

    def _step_record(self, orm: AgentStepORM) -> AgentStepRecord:
        return AgentStepRecord(
            schema_version=orm.schema_version or "1.0",
            step_id=orm.step_id,
            run_id=orm.run_id,
            step_sequence=orm.step_no,
            agent_name=orm.agent_name,
            node_name=orm.node_name or orm.agent_name,
            action=orm.action,
            status=orm.status,
            generation_attempt=orm.generation_attempt or 1,
            input_summary=orm.input_summary,
            output_summary=orm.output_summary,
            decision_reason=orm.decision_reason,
            evidence_refs=orm.evidence_refs or [],
            resource_ids=orm.resource_ids or [],
            review_ids=orm.review_ids or [],
            retry_count=orm.retry_count or 0,
            error_code=orm.error_code,
            error_message=orm.error_message,
            llm_call_id=orm.llm_call_id,
            model_name=orm.model_name,
            provider_request_id=orm.provider_request_id,
            structured_output_mode=orm.structured_output_mode,
            finish_reason=orm.finish_reason,
            input_tokens=orm.input_tokens,
            output_tokens=orm.output_tokens,
            total_tokens=orm.total_tokens,
            llm_duration_ms=orm.llm_duration_ms,
            llm_attempts=orm.llm_attempts or [],
            retrieval_status=orm.retrieval_status,
            retrieval_config_hash=orm.retrieval_config_hash,
            retrieval_query_hashes=orm.retrieval_query_hashes or [],
            retrieval_candidate_count=orm.retrieval_candidate_count,
            retrieval_dropped_candidate_count=orm.retrieval_dropped_candidate_count,
            retrieval_partial_failure_count=orm.retrieval_partial_failure_count,
            payload_hash=orm.payload_hash,
            started_at=_as_utc(orm.started_at) or _utcnow(),
            ended_at=_as_utc(orm.ended_at),
            duration_ms=orm.duration_ms,
        )

    def _event_record(self, orm: WorkflowEventORM) -> WorkflowEvent:
        return WorkflowEvent(
            schema_version=orm.schema_version or "1.0",
            event_id=orm.event_id,
            run_id=orm.run_id,
            event_sequence=orm.event_sequence,
            event_type=WorkflowEventType(orm.event_type),
            step_id=orm.step_id,
            step_sequence=orm.step_sequence,
            node_name=orm.node_name,
            status=orm.status,
            payload=orm.payload or {},
            payload_hash=orm.payload_hash,
            error_code=orm.error_code,
            occurred_at=_as_utc(orm.occurred_at) or _utcnow(),
            persisted_at=_as_utc(orm.persisted_at),
        )

    def _checkpoint_record(self, orm: WorkflowCheckpointORM) -> WorkflowCheckpoint:
        return WorkflowCheckpoint(
            schema_version=orm.schema_version or "1.0",
            checkpoint_id=orm.checkpoint_id,
            run_id=orm.run_id,
            event_sequence=orm.event_sequence,
            step_id=orm.step_id,
            step_sequence=orm.step_sequence,
            node_name=orm.node_name,
            state_projection=orm.state_projection or {},
            state_hash=orm.state_hash,
            created_at=_as_utc(orm.created_at) or _utcnow(),
        )

    def _evidence_record(
        self, orm: RetrievalEvidenceSnapshotORM
    ) -> PersistedEvidenceSnapshot:
        locator_payload = dict(orm.locator or {})
        locator_payload["source_type"] = SourceType(locator_payload["source_type"])
        return PersistedEvidenceSnapshot(
            schema_version=orm.schema_version or "1.0",
            evidence_id=orm.evidence_id,
            run_id=orm.run_id,
            retrieval_step_id=orm.retrieval_step_id,
            knowledge_base_id=orm.knowledge_base_id,
            document_id=orm.document_id,
            document_version=orm.document_version,
            chunk_id=orm.chunk_id,
            query_hash=orm.query_hash,
            query_rank=orm.query_rank,
            rank=orm.rank,
            raw_score=orm.raw_score,
            score_kind=orm.score_kind,
            normalized_score=orm.normalized_score,
            excerpt=orm.excerpt,
            excerpt_hash=orm.excerpt_hash,
            locator=SourceLocator.model_validate(locator_payload),
            config_hash=orm.config_hash,
            snapshot_hash=orm.snapshot_hash,
            retrieved_at=_as_utc(orm.retrieved_at) or _utcnow(),
            persisted_at=_as_utc(orm.persisted_at),
        )

    @staticmethod
    def _require_run(db: Session, run_id: str) -> AgentRunORM:
        orm = db.query(AgentRunORM).filter_by(run_id=run_id).with_for_update().first()
        if orm is None:
            raise RunNotFound("run not found")
        return orm

    def _append_event(
        self,
        db: Session,
        run: AgentRunORM,
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
    ) -> WorkflowEventORM:
        event_id = event_id or str(uuid.uuid4())
        existing = db.get(WorkflowEventORM, event_id)
        if existing is not None:
            if (
                existing.run_id == run.run_id
                and existing.event_type == event_type.value
                and existing.payload_hash == canonical_hash(payload)
                and existing.step_id == step_id
                and existing.status == status
                and existing.error_code == error_code
            ):
                return existing
            raise PersistenceConflict("event id conflicts with durable state")
        sequence = (run.last_event_sequence or 0) + 1
        event = WorkflowEvent(
            event_id=event_id,
            run_id=run.run_id,
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
        orm = WorkflowEventORM(**event.model_dump(mode="python"))
        orm.event_type = event.event_type.value
        run.last_event_sequence = sequence
        run.updated_at = _utcnow()
        run.row_version = (run.row_version or 0) + 1
        db.add(orm)
        return orm

    def create_run(self, command: CreateRunCommand) -> AgentRunRecord:
        with self.session_factory() as db:
            existing = db.get(AgentRunORM, command.run_id)
            if existing is not None:
                if existing.request_hash != command.request_hash:
                    raise PersistenceConflict("run id conflicts with another request")
                return self._run_record(existing)
            orm = AgentRunORM(
                run_id=command.run_id,
                schema_version="1.0",
                learner_id=command.learner_id,
                knowledge_base_id=command.knowledge_base_id,
                topic=command.topic,
                status=RunStatus.CREATED.value,
                request_hash=command.request_hash,
                workflow_status=None,
                execution_status=None,
                current_node="pending",
                current_step_sequence=0,
                last_event_sequence=0,
                generation_attempt=1,
                revision_count=0,
                retrieval_status="pending",
                replay_completeness=ReplayCompleteness.COMPLETE.value,
                owner_instance_id=command.owner_instance_id,
                lease_expires_at=command.lease_expires_at,
                input_payload=command.request_snapshot,
                output_payload={},
                started_at=None,
                updated_at=command.occurred_at,
                row_version=1,
            )
            db.add(orm)
            db.flush()
            # Older SQLite schemas may retain a server default on started_at.
            orm.started_at = None
            self._append_event(
                db,
                orm,
                WorkflowEventType.RUN_CREATED,
                payload={"request_hash": command.request_hash},
                occurred_at=command.occurred_at,
                status=RunStatus.CREATED.value,
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("run create conflict") from exc
            db.refresh(orm)
            return self._run_record(orm)

    def start_run(
        self,
        run_id: str,
        *,
        occurred_at: datetime,
        lease_expires_at: datetime | None = None,
    ) -> AgentRunRecord:
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            if run.status != RunStatus.RUNNING.value:
                require_run_transition(run.status, RunStatus.RUNNING)
                run.status = RunStatus.RUNNING.value
                run.workflow_status = "running"
                run.execution_status = "running"
                run.started_at = occurred_at
                run.heartbeat_at = occurred_at
                run.lease_expires_at = lease_expires_at
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.RUN_STARTED,
                    payload={},
                    occurred_at=occurred_at,
                    status=RunStatus.RUNNING.value,
                )
                db.commit()
                db.refresh(run)
            return self._run_record(run)

    def begin_step(self, command: BeginStepCommand) -> AgentStepRecord:
        with self.session_factory() as db:
            run = self._require_run(db, command.run_id)
            if run.status != RunStatus.RUNNING.value:
                raise PersistenceConflict("step can only begin while run is running")
            existing = db.get(AgentStepORM, command.step_id)
            if existing is not None:
                if existing.run_id == command.run_id and existing.step_no == command.step_sequence:
                    return self._step_record(existing)
                raise PersistenceConflict("step id conflicts with durable state")
            if command.step_sequence != (run.current_step_sequence or 0) + 1:
                raise PersistenceConflict("step sequence is not monotonic")
            step = AgentStepORM(
                step_id=command.step_id,
                schema_version="1.0",
                run_id=command.run_id,
                step_no=command.step_sequence,
                agent_name=command.agent_name,
                node_name=command.node_name,
                action=command.action,
                status="running",
                generation_attempt=command.generation_attempt,
                input_payload={},
                output_payload={},
                started_at=command.started_at,
            )
            db.add(step)
            run.current_step_id = command.step_id
            run.current_step_sequence = command.step_sequence
            run.current_node = command.node_name
            run.generation_attempt = command.generation_attempt
            run.heartbeat_at = command.started_at
            if command.lease_expires_at is not None:
                run.lease_expires_at = command.lease_expires_at
            self._append_event(
                db,
                run,
                WorkflowEventType.STEP_STARTED,
                payload={"attempt": command.generation_attempt},
                occurred_at=command.started_at,
                step_id=command.step_id,
                step_sequence=command.step_sequence,
                node_name=command.node_name,
                status="running",
            )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("step/event sequence conflict") from exc
            db.refresh(step)
            return self._step_record(step)

    def complete_step(self, command: CompleteStepCommand) -> AgentStepRecord:
        with self.session_factory() as db:
            run = self._require_run(db, command.run_id)
            step = db.query(AgentStepORM).filter_by(step_id=command.step_id).with_for_update().first()
            if step is None:
                raise RunNotFound("step not found")
            trace = dict(command.trace)
            if trace.get("run_id") not in {None, command.run_id}:
                raise PersistenceConflict("trace run id mismatch")
            if trace.get("step_id") not in {None, command.step_id}:
                raise PersistenceConflict("trace step id mismatch")
            hash_payload = {
                key: trace.get(key)
                for key in (
                    "status", "attempt", "input_summary", "output_summary",
                    "decision_reason", "evidence_refs", "resource_ids", "review_ids",
                    "retry_count", "error_code", "llm_call_id", "model_name",
                    "provider_request_id", "structured_output_mode", "finish_reason",
                    "input_tokens", "output_tokens", "total_tokens", "llm_duration_ms",
                    "llm_attempts", "retrieval_status", "retrieval_config_hash",
                    "retrieval_query_hashes", "retrieval_candidate_count",
                    "retrieval_dropped_candidate_count", "retrieval_partial_failure_count",
                )
                if trace.get(key) is not None
            }
            payload_hash = canonical_hash(hash_payload)
            if step.status != "running":
                if step.payload_hash == payload_hash:
                    return self._step_record(step)
                raise PersistenceConflict("terminal step cannot be changed")
            step.status = str(trace.get("status") or "failed")
            step.generation_attempt = int(trace.get("attempt") or step.generation_attempt or 1)
            step.input_summary = trace.get("input_summary")
            step.output_summary = trace.get("output_summary")
            step.decision_reason = trace.get("decision_reason")
            step.evidence_refs = list(trace.get("evidence_refs") or [])
            step.resource_ids = list(trace.get("resource_ids") or [])
            step.review_ids = list(trace.get("review_ids") or [])
            step.retry_count = int(trace.get("retry_count") or 0)
            step.error_code = trace.get("error_code")
            step.error_message = trace.get("error_message")
            step.llm_call_id = trace.get("llm_call_id")
            step.model_name = trace.get("model_name")
            step.provider_request_id = trace.get("provider_request_id")
            step.structured_output_mode = trace.get("structured_output_mode")
            step.finish_reason = trace.get("finish_reason")
            step.input_tokens = trace.get("input_tokens")
            step.output_tokens = trace.get("output_tokens")
            step.total_tokens = trace.get("total_tokens")
            step.llm_duration_ms = trace.get("llm_duration_ms")
            step.llm_attempts = trace.get("llm_attempts") or []
            step.retrieval_status = trace.get("retrieval_status")
            step.retrieval_config_hash = trace.get("retrieval_config_hash")
            step.retrieval_query_hashes = trace.get("retrieval_query_hashes") or []
            step.retrieval_candidate_count = trace.get("retrieval_candidate_count")
            step.retrieval_dropped_candidate_count = trace.get("retrieval_dropped_candidate_count")
            step.retrieval_partial_failure_count = trace.get("retrieval_partial_failure_count")
            step.payload_hash = payload_hash
            step.ended_at = command.ended_at
            started_at = _as_utc(step.started_at) or command.ended_at
            step.duration_ms = max(0, int((command.ended_at - started_at).total_seconds() * 1000))
            run.generation_attempt = step.generation_attempt
            run.retrieval_status = step.retrieval_status or run.retrieval_status
            run.last_error_code = step.error_code
            terminal_event = (
                WorkflowEventType.STEP_DEGRADED
                if step.status == "degraded"
                else WorkflowEventType.STEP_FAILED
                if step.status in {"failed", "retryable_error"}
                else WorkflowEventType.STEP_SUCCEEDED
            )
            self._append_event(
                db,
                run,
                terminal_event,
                payload={
                    "attempt": step.generation_attempt,
                    "retry_count": step.retry_count,
                    "evidence_ids": step.evidence_refs,
                    "resource_ids": step.resource_ids,
                    "review_ids": step.review_ids,
                },
                occurred_at=command.ended_at,
                step_id=step.step_id,
                step_sequence=step.step_no,
                node_name=step.node_name or step.agent_name,
                status=step.status,
                error_code=step.error_code,
            )
            saved_ids: list[str] = []
            for snapshot in command.evidence:
                if snapshot.run_id != command.run_id or snapshot.retrieval_step_id != command.step_id:
                    raise PersistenceConflict("evidence is outside the current run/step")
                if run.knowledge_base_id and snapshot.knowledge_base_id != run.knowledge_base_id:
                    raise PersistenceConflict("evidence is outside the current knowledge base")
                existing = db.get(RetrievalEvidenceSnapshotORM, snapshot.evidence_id)
                if existing is not None:
                    if existing.snapshot_hash != snapshot.snapshot_hash:
                        raise PersistenceConflict("evidence snapshot is immutable")
                    continue
                payload = snapshot.model_dump(mode="python")
                payload["locator"] = snapshot.locator.model_dump(mode="json")
                db.add(RetrievalEvidenceSnapshotORM(**payload))
                saved_ids.append(snapshot.evidence_id)
            if saved_ids:
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.EVIDENCE_SNAPSHOT_SAVED,
                    payload={"evidence_ids": saved_ids, "count": len(saved_ids)},
                    occurred_at=command.ended_at,
                    step_id=step.step_id,
                    step_sequence=step.step_no,
                    node_name=step.node_name or step.agent_name,
                    status=step.status,
                )
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("step completion conflict") from exc
            db.refresh(step)
            return self._step_record(step)

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
        if canonical_hash(state_projection) != state_hash:
            raise PersistenceConflict("checkpoint hash mismatch")
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            existing = db.query(WorkflowCheckpointORM).filter_by(run_id=run_id, step_id=step_id).first()
            if existing is not None:
                if existing.state_hash == state_hash:
                    return self._checkpoint_record(existing)
                raise PersistenceConflict("checkpoint for step is immutable")
            event = self._append_event(
                db,
                run,
                WorkflowEventType.CHECKPOINT_SAVED,
                payload={"state_hash": state_hash},
                occurred_at=occurred_at,
                step_id=step_id,
                step_sequence=step_sequence,
                node_name=node_name,
                status="saved",
            )
            db.flush()
            checkpoint = WorkflowCheckpointORM(
                checkpoint_id=str(uuid.uuid4()),
                schema_version="1.0",
                run_id=run_id,
                event_sequence=event.event_sequence,
                step_id=step_id,
                step_sequence=step_sequence,
                node_name=node_name,
                state_projection=state_projection,
                state_hash=state_hash,
                created_at=occurred_at,
            )
            db.add(checkpoint)
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("checkpoint conflict") from exc
            db.refresh(checkpoint)
            return self._checkpoint_record(checkpoint)

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
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            if run.status != RunStatus.FINALIZING.value:
                require_run_transition(run.status, RunStatus.FINALIZING)
                run.status = RunStatus.FINALIZING.value
                run.workflow_status = workflow_status
                run.execution_status = "finalizing"
                run.current_node = current_node
                run.generation_attempt = generation_attempt
                run.revision_count = revision_count
                run.retrieval_status = retrieval_status
                run.final_decision = final_decision
                run.heartbeat_at = occurred_at
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.RUN_FINALIZING,
                    payload={"workflow_status": workflow_status},
                    occurred_at=occurred_at,
                    status=RunStatus.FINALIZING.value,
                )
                db.commit()
                db.refresh(run)
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
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            if run.status != status.value:
                require_run_transition(run.status, status)
                run.status = status.value
                run.workflow_status = workflow_status
                run.execution_status = execution_status
                run.final_decision = final_decision
                run.ended_at = occurred_at
                run.heartbeat_at = occurred_at
                run.lease_expires_at = None
                run.output_payload = {
                    "workflow_status": workflow_status,
                    "final_decision": final_decision,
                }
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.RUN_FAILED if status == RunStatus.FAILED else WorkflowEventType.RUN_COMPLETED,
                    payload={"workflow_status": workflow_status},
                    occurred_at=occurred_at,
                    status=status.value,
                    error_code=run.last_error_code if status == RunStatus.FAILED else None,
                )
                db.commit()
                db.refresh(run)
            return self._run_record(run)

    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        occurred_at: datetime,
    ) -> AgentRunRecord:
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            if run.status != RunStatus.FAILED.value:
                require_run_transition(run.status, RunStatus.FAILED)
                run.status = RunStatus.FAILED.value
                run.workflow_status = "failed"
                run.execution_status = "failed"
                run.last_error_code = error_code
                run.ended_at = occurred_at
                run.heartbeat_at = occurred_at
                run.lease_expires_at = None
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.RUN_FAILED,
                    payload={},
                    occurred_at=occurred_at,
                    status=RunStatus.FAILED.value,
                    error_code=error_code,
                )
                db.commit()
                db.refresh(run)
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
        with self.session_factory() as db:
            run = self._require_run(db, run_id)
            event = self._append_event(
                db,
                run,
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
            try:
                db.commit()
            except IntegrityError as exc:
                db.rollback()
                raise PersistenceConflict("event sequence conflict") from exc
            db.refresh(event)
            return self._event_record(event)

    def get_run(self, run_id: str) -> AgentRunRecord | None:
        with self.session_factory() as db:
            orm = db.get(AgentRunORM, run_id)
            return self._run_record(orm) if orm else None

    def list_steps(self, run_id: str) -> list[AgentStepRecord]:
        with self.session_factory() as db:
            rows = db.query(AgentStepORM).filter_by(run_id=run_id).order_by(AgentStepORM.step_no).all()
            return [self._step_record(item) for item in rows]

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkflowEvent]:
        with self.session_factory() as db:
            rows = (
                db.query(WorkflowEventORM)
                .filter(WorkflowEventORM.run_id == run_id)
                .filter(WorkflowEventORM.event_sequence > after_sequence)
                .order_by(WorkflowEventORM.event_sequence)
                .limit(limit)
                .all()
            )
            return [self._event_record(item) for item in rows]

    def list_checkpoints(self, run_id: str) -> list[WorkflowCheckpoint]:
        with self.session_factory() as db:
            rows = (
                db.query(WorkflowCheckpointORM)
                .filter_by(run_id=run_id)
                .order_by(WorkflowCheckpointORM.step_sequence)
                .all()
            )
            return [self._checkpoint_record(item) for item in rows]

    def list_evidence(self, run_id: str) -> list[PersistedEvidenceSnapshot]:
        with self.session_factory() as db:
            rows = (
                db.query(RetrievalEvidenceSnapshotORM)
                .filter_by(run_id=run_id)
                .order_by(RetrievalEvidenceSnapshotORM.rank, RetrievalEvidenceSnapshotORM.evidence_id)
                .all()
            )
            return [self._evidence_record(item) for item in rows]

    def mark_stale_interrupted(self, *, before: datetime, occurred_at: datetime) -> int:
        with self.session_factory() as db:
            runs = (
                db.query(AgentRunORM)
                .filter(AgentRunORM.status.in_([RunStatus.RUNNING.value, RunStatus.FINALIZING.value]))
                .filter(AgentRunORM.lease_expires_at.is_not(None))
                .filter(AgentRunORM.lease_expires_at < before)
                .with_for_update()
                .all()
            )
            for run in runs:
                require_run_transition(run.status, RunStatus.INTERRUPTED)
                run.status = RunStatus.INTERRUPTED.value
                run.execution_status = "interrupted"
                run.ended_at = occurred_at
                run.last_error_code = "WORKFLOW_RUN_INTERRUPTED"
                run.lease_expires_at = None
                self._append_event(
                    db,
                    run,
                    WorkflowEventType.RUN_INTERRUPTED,
                    payload={},
                    occurred_at=occurred_at,
                    status=RunStatus.INTERRUPTED.value,
                    error_code="WORKFLOW_RUN_INTERRUPTED",
                )
            db.commit()
            return len(runs)

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
        self.create_run(
            CreateRunCommand(
                run_id=run_id,
                learner_id=learner_id,
                knowledge_base_id=knowledge_base_id,
                topic=topic,
                request_snapshot=input_payload,
                request_hash=canonical_hash(input_payload),
                occurred_at=now,
            )
        )
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
            self.complete_step(CompleteStepCommand(run_id=run_id, step_id=step_id, trace=item, ended_at=now))
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
        requested_id = review.get("review_ids", {}).get(resource_id)
        legacy_batch_id = review.get("review_id")
        review_id = requested_id or (f"{legacy_batch_id}:{resource_id}" if legacy_batch_id else str(uuid.uuid4()))
        status = review.get("status") or ("passed" if review.get("passed") else "needs_review")
        claims = [_as_dict(claim) for claim in review.get("claims", [])]
        claim_total = review.get("claim_total", len(claims))
        claim_supported = review.get("claim_supported", sum(bool(claim.get("supported")) for claim in claims))
        claim_unsupported = review.get("claim_unsupported", max(0, claim_total - claim_supported))
        hallucination_rate = review.get("hallucination_rate", review.get("hallucination_score", 0.0))
        with self.session_factory() as db:
            existing = db.get(ResourceReviewORM, review_id)
            if existing is not None:
                return review_id
            db.add(
                ResourceReviewORM(
                    review_id=review_id,
                    resource_id=resource_id,
                    run_id=run_id,
                    status=status,
                    claim_total=claim_total,
                    claim_supported=claim_supported,
                    claim_unsupported=claim_unsupported,
                    suspected_hallucinations=review.get("suspected_hallucinations", claim_unsupported),
                    hallucination_rate=hallucination_rate,
                    review_pass_rate=review.get(
                        "review_pass_rate",
                        1.0 if status in {"approve", "approved", "passed"} else 0.0,
                    ),
                    revision_count=review.get("revision_count", 0),
                    issues=review.get("issues", []),
                )
            )
            for claim in claims:
                db.add(
                    ResourceClaimORM(
                        claim_id=str(claim.get("claim_id") or uuid.uuid4()),
                        review_id=review_id,
                        resource_id=resource_id,
                        knowledge_point=claim.get("knowledge_point"),
                        claim_text=claim.get("text") or claim.get("claim_text", ""),
                        supported=bool(claim.get("supported", False)),
                        confidence=claim.get("confidence"),
                        evidence_refs=[_as_dict(ref) for ref in claim.get("evidence_refs", [])],
                        issue_type=claim.get("issue_type"),
                        correction=claim.get("correction"),
                        review_comment=claim.get("review_comment"),
                    )
                )
            db.commit()
        return review_id

    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        with self.session_factory() as db:
            review = (
                db.query(ResourceReviewORM)
                .filter_by(resource_id=resource_id)
                .order_by(ResourceReviewORM.created_at.desc())
                .first()
            )
            if review is None:
                return None
            claims = (
                db.query(ResourceClaimORM)
                .filter_by(review_id=review.review_id)
                .order_by(ResourceClaimORM.claim_id)
                .all()
            )
            return ReviewSummary(
                review_id=review.review_id,
                resource_id=review.resource_id,
                status=review.status,
                claim_total=review.claim_total,
                claim_supported=review.claim_supported,
                claim_unsupported=review.claim_unsupported,
                suspected_hallucinations=review.suspected_hallucinations,
                hallucination_rate=review.hallucination_rate,
                review_pass_rate=review.review_pass_rate,
                revision_count=review.revision_count,
                issues=review.issues or [],
                claims=[
                    ResourceClaim(
                        claim_id=claim.claim_id,
                        text=claim.claim_text,
                        knowledge_point=claim.knowledge_point,
                        supported=claim.supported,
                        confidence=claim.confidence,
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
                            for ref in (claim.evidence_refs or [])
                        ],
                        issue_type=claim.issue_type,
                        correction=claim.correction,
                        review_comment=claim.review_comment,
                    )
                    for claim in claims
                ],
            )
