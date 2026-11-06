"""Repository contract for the independent LLM-call accounting store."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from app.models.shared.llm_accounting import (
    LLMCallObservationV1,
    SegmentInfoV1,
    SegmentSubmissionV1,
)


class AccountingRecordConflict(RuntimeError):
    """Duplicate primary key with a different payload hash (kept first value)."""


@dataclass
class TaskAccountingRecords:
    """Everything persisted for one (domain, run_id) task identity."""

    segments: list[SegmentInfoV1] = field(default_factory=list)
    calls: list[LLMCallObservationV1] = field(default_factory=list)
    conflicts: int = 0
    unavailable_reasons: list[str] = field(default_factory=list)


class BaseLLMAccountingRepository(Protocol):
    """Persist and read sealed accounting segment snapshots.

    Duplicate delivery of the same primary key with the same payload hash is
    an idempotent no-op; a different hash under the same primary key never
    overwrites the first value and is tracked as a conflict.
    """

    def save_segment(self, submission: SegmentSubmissionV1) -> str:
        """Persist one sealed segment snapshot; returns received|duplicate|conflict|partial."""
        ...

    def get_task(self, domain: str, run_id: str) -> TaskAccountingRecords: ...

    def purge_task(self, domain: str, run_id: str) -> int: ...

    def close(self) -> None: ...


def create_llm_accounting_repository(path: str | None) -> BaseLLMAccountingRepository:
    """Build the SQL repository for ``path``; a falsy path yields memory-only."""

    from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository

    if not path:
        from app.db.audit.llm_accounting.memory import MemoryLLMAccountingRepository

        return MemoryLLMAccountingRepository()
    return SQLLLMAccountingRepository(path)
