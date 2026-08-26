"""Persist merge-boundary checkpoints while consuming a synchronous LangGraph."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.base import BaseAuditRepository, PersistenceConflict
from app.models.shared.persistence import (
    BeginStepCommand,
    CompleteStepCommand,
    canonical_hash,
    canonical_json,
    build_checkpoint_projection,
)


class DurableWorkflowRunner:
    def __init__(self, workflow: Any, repository: BaseAuditRepository, artifact_recorder: Any | None = None):
        self.workflow = workflow
        self.repository = repository
        self.artifact_recorder = artifact_recorder

    def invoke(self, initial_state: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.workflow, "stream"):
            raw_result = self.workflow.invoke(initial_state)
            result = {**initial_state, **raw_result}
            if "workflow_status" not in raw_result:
                result["workflow_status"] = "completed"
            self._record_compatibility_trace(result)
            return result

        latest: dict[str, Any] = initial_state
        checkpointed: set[str] = set()
        for value in self.workflow.stream(initial_state, stream_mode="values"):
            if not isinstance(value, dict):
                continue
            latest = value
            trace = latest.get("trace", [])
            if not trace:
                continue
            item = trace[-1]
            if not isinstance(item, dict) or not item.get("step_id"):
                continue
            step_id = str(item["step_id"])
            if step_id in checkpointed:
                continue
            if self.artifact_recorder is not None:
                try:
                    self.artifact_recorder.record(latest, item)
                except Exception as exc:
                    code = (
                        ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                        if isinstance(exc, PersistenceConflict)
                        else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                    )
                    raise ApplicationError(
                        code,
                        status_code=409 if isinstance(exc, PersistenceConflict) else 503,
                    ) from exc
            projection = build_checkpoint_projection(latest)
            encoded = canonical_json(projection).encode("utf-8")
            if len(encoded) > get_settings().workflow_checkpoint_max_bytes:
                raise ApplicationError(ErrorCode.WORKFLOW_CHECKPOINT_INVALID, status_code=500)
            try:
                self.repository.save_checkpoint(
                    run_id=str(initial_state["run_id"]),
                    step_id=step_id,
                    step_sequence=int(item["sequence"]),
                    node_name=str(item.get("node_name") or item.get("agent_name") or "unknown"),
                    state_projection=projection,
                    state_hash=canonical_hash(projection),
                    occurred_at=datetime.now(timezone.utc),
                )
            except Exception as exc:
                code = (
                    ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                    if isinstance(exc, PersistenceConflict)
                    else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                )
                raise ApplicationError(code, status_code=409 if isinstance(exc, PersistenceConflict) else 503) from exc
            checkpointed.add(step_id)
        return latest

    def _record_compatibility_trace(self, result: dict[str, Any]) -> None:
        """Record non-LangGraph test doubles without weakening the production wrapper."""

        run_id = str(result["run_id"])
        existing_ids = {item.step_id for item in self.repository.list_steps(run_id)}
        traces = [dict(item) for item in result.get("trace", []) if isinstance(item, dict)]
        resources = [
            item for item in result.get("generated_resources", []) if hasattr(item, "resource_id")
        ]
        agents = {str(item.get("agent_name") or "") for item in traces}
        if resources and "generator" not in agents:
            traces.insert(0, {
                "step_id": f"{run_id}:compat-generator",
                "agent_name": "generator",
                "node_name": "generator",
                "action": "compatibility artifact boundary",
                "status": "success",
                "resource_ids": [item.resource_id for item in resources],
            })

        for sequence, raw in enumerate(traces, start=1):
            if not isinstance(raw, dict):
                continue
            trace = dict(raw)
            step_id = str(trace.get("step_id") or f"{run_id}:{sequence}")
            if step_id in existing_ids:
                continue
            trace.update(run_id=run_id, step_id=step_id, sequence=sequence)
            if trace.get("agent_name") == "generator" and not trace.get("resource_ids"):
                trace["resource_ids"] = [item.resource_id for item in resources]
            started_at = datetime.now(timezone.utc)
            self.repository.begin_step(
                BeginStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    step_sequence=sequence,
                    node_name=str(trace.get("node_name") or trace.get("agent_name") or "test_double"),
                    agent_name=str(trace.get("agent_name") or "test_double"),
                    action=str(trace.get("action") or "test double"),
                    generation_attempt=int(trace.get("attempt") or 1),
                    started_at=started_at,
                )
            )
            # Test doubles use invoke() rather than LangGraph streaming. They
            # still honor the production ownership rule: artifacts are durable
            # before the corresponding compatibility checkpoint is accepted.
            if self.artifact_recorder is not None:
                try:
                    self.artifact_recorder.record(result, trace)
                except Exception as exc:
                    code = (
                        ErrorCode.WORKFLOW_PERSISTENCE_CONFLICT
                        if isinstance(exc, PersistenceConflict)
                        else ErrorCode.WORKFLOW_PERSISTENCE_UNAVAILABLE
                    )
                    raise ApplicationError(
                        code,
                        status_code=409 if isinstance(exc, PersistenceConflict) else 503,
                    ) from exc
            self.repository.complete_step(
                CompleteStepCommand(
                    run_id=run_id,
                    step_id=step_id,
                    trace=trace,
                    ended_at=datetime.now(timezone.utc),
                )
            )
            projection = build_checkpoint_projection(result)
            self.repository.save_checkpoint(
                run_id=run_id,
                step_id=step_id,
                step_sequence=sequence,
                node_name=str(trace.get("node_name") or trace.get("agent_name") or "test_double"),
                state_projection=projection,
                state_hash=canonical_hash(projection),
                occurred_at=datetime.now(timezone.utc),
            )
