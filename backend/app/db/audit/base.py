from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable, Optional

from app.models.shared.persistence import (
    AgentRunRecord,
    AgentStepRecord,
    BeginStepCommand,
    CompleteStepCommand,
    CreateRunCommand,
    PersistedEvidenceSnapshot,
    RunStatus,
    WorkflowCheckpoint,
    WorkflowEvent,
    WorkflowEventType,
)
from app.models.learning_documents.schemas import ReviewSummary


REVIEW_NODE_NAMES = frozenset({"review", "reviewer"})
# Controlled failure codes for the batch ledger read.  Exception text never
# leaves this layer, so provider/driver detail cannot reach a public DTO.
AUDIT_INVALID = "AUDIT_INVALID"
AUDIT_MISSING = "AUDIT_MISSING"
AUDIT_READ_FAILED = "AUDIT_READ_FAILED"
RUN_FACTS_UNAVAILABLE = "RUN_FACTS_UNAVAILABLE"


@dataclass(frozen=True)
class StepReviewAudit:
    """One review step's validated private ledger, or a controlled failure."""

    run_id: str
    step_id: str
    step_sequence: int
    node_name: str
    status: str
    audit: Any | None = None
    failure_code: str | None = None


class PersistenceError(RuntimeError):
    """Sanitized base failure for lifecycle persistence."""


class PersistenceConflict(PersistenceError):
    """The requested idempotent mutation conflicts with durable state."""


class RunNotFound(PersistenceError):
    """The requested Run does not exist."""


def audit_failure_code(error: Exception) -> str:
    """Map a ledger validation failure to a controlled code, never its text."""
    message = str(error).lower()
    if "missing" in message or "incomplete" in message:
        return AUDIT_MISSING
    if isinstance(error, PersistenceError) or "mismatch" in message or "invalid" in message:
        return AUDIT_INVALID
    return AUDIT_READ_FAILED


class BaseAuditRepository(ABC):
    def validate_review_execution_epoch(self, run_id: str, owner: str, epoch: int) -> None:
        """Repositories without a durable dispatch ledger cannot verify an epoch."""
        raise PersistenceConflict("review execution epoch cannot be verified")

    """持久化 Agent 过程与资源审核结果的抽象接口。"""

    def get_step_review_audit(self, run_id: str, step_id: str):
        """Internal only; legacy custom repositories may have no private ledger."""
        return None

    def get_review_audits_by_runs(self, run_ids: list[str]) -> list[StepReviewAudit]:
        """Batch private-ledger read with a bounded, ordered result.

        This compatibility implementation reuses the single-step validation
        core, so a custom legacy repository keeps working without a new
        abstract method.  Native repositories override it with one batched
        load per run.  A damaged step never hides its siblings: it becomes a
        controlled failure code instead of an exception.
        """
        results: list[StepReviewAudit] = []
        for run_id in dict.fromkeys(run_ids):
            try:
                steps = self.list_steps(run_id)
            except Exception:
                results.append(StepReviewAudit(
                    run_id=run_id, step_id="", step_sequence=-1,
                    node_name="", status="", failure_code=RUN_FACTS_UNAVAILABLE,
                ))
                continue
            for step in steps:
                if (step.node_name or step.agent_name) not in REVIEW_NODE_NAMES:
                    continue
                try:
                    audit = self.get_step_review_audit(run_id, step.step_id)
                except Exception as exc:  # noqa: BLE001 - fail closed per step
                    results.append(StepReviewAudit(
                        run_id=run_id, step_id=step.step_id,
                        step_sequence=step.step_sequence,
                        node_name=step.node_name or step.agent_name,
                        status=step.status, failure_code=audit_failure_code(exc),
                    ))
                    continue
                results.append(StepReviewAudit(
                    run_id=run_id, step_id=step.step_id,
                    step_sequence=step.step_sequence,
                    node_name=step.node_name or step.agent_name,
                    status=step.status, audit=audit,
                ))
        return sorted(results, key=lambda item: (item.run_id, item.step_sequence, item.step_id))

    @abstractmethod
    def save_run(
        self,
        learner_id: str,
        knowledge_base_id: Optional[str],
        topic: str,
        trace: Iterable[dict[str, Any]],
        input_payload: dict[str, Any],
        output_payload: dict[str, Any],
        status: str,
        run_id: Optional[str] = None,
    ) -> str:
        pass

    @abstractmethod
    def save_review(self, resource_id: str, review: dict[str, Any], run_id: Optional[str]) -> str:
        pass

    def get_reviews_by_resources(self, resource_ids: list[str]) -> dict:
        return {resource_id: self.get_review_by_resource(resource_id) for resource_id in dict.fromkeys(resource_ids)}

    @abstractmethod
    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        """获取资源最近一次审核及其 Claim 证据。"""

    @abstractmethod
    def list_reviews_by_run(self, run_id: str) -> list[dict[str, Any]]:
        """按稳定顺序读取一次 Run 的全部审核轮次。"""
        pass

    @abstractmethod
    def create_run(self, command: CreateRunCommand) -> AgentRunRecord:
        pass

    @abstractmethod
    def start_run(
        self,
        run_id: str,
        *,
        occurred_at: datetime,
        lease_expires_at: datetime | None = None,
    ) -> AgentRunRecord:
        pass

    @abstractmethod
    def begin_step(self, command: BeginStepCommand) -> AgentStepRecord:
        pass

    @abstractmethod
    def complete_step(self, command: CompleteStepCommand) -> AgentStepRecord:
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def fail_run(
        self,
        run_id: str,
        *,
        error_code: str,
        occurred_at: datetime,
    ) -> AgentRunRecord:
        pass

    @abstractmethod
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
        pass

    @abstractmethod
    def get_run_creation_snapshot(self, run_id: str) -> dict:
        raise PersistenceError("creation snapshot unavailable")

    def get_run(self, run_id: str) -> AgentRunRecord | None:
        pass

    @abstractmethod
    def list_steps(self, run_id: str) -> list[AgentStepRecord]:
        pass

    @abstractmethod
    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> list[WorkflowEvent]:
        pass

    @abstractmethod
    def list_checkpoints(self, run_id: str) -> list[WorkflowCheckpoint]:
        pass

    @abstractmethod
    def list_evidence(self, run_id: str) -> list[PersistedEvidenceSnapshot]:
        pass

    @abstractmethod
    def mark_stale_interrupted(self, *, before: datetime, occurred_at: datetime) -> int:
        pass
