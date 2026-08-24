from abc import ABC, abstractmethod
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


class PersistenceError(RuntimeError):
    """Sanitized base failure for lifecycle persistence."""


class PersistenceConflict(PersistenceError):
    """The requested idempotent mutation conflicts with durable state."""


class RunNotFound(PersistenceError):
    """The requested Run does not exist."""


class BaseAuditRepository(ABC):
    """持久化 Agent 过程与资源审核结果的抽象接口。"""

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
