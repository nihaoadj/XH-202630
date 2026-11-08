"""SQL/Memory repository semantics for the independent accounting store."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from app.db.audit.llm_accounting.memory import MemoryLLMAccountingRepository
from app.db.audit.llm_accounting.sql_repository import SQLLLMAccountingRepository
from app.models.shared.llm_accounting import (
    LLMCallObservationV1,
    SegmentInfoV1,
    SegmentSubmissionV1,
    AccountingSegmentV1,
)


def _segment(run_id="run-1", segment_id="seg-1", calls=1, sealed=True) -> AccountingSegmentV1:
    observations = [
        LLMCallObservationV1(
            domain="learning_documents",
            run_id=run_id,
            segment_id=segment_id,
            observation_id=index + 1,
            stage="generate",
            attempts=[],
            known_input_tokens=10,
        )
        for index in range(calls)
    ]
    return AccountingSegmentV1(
        domain="learning_documents",
        run_id=run_id,
        segment_id=segment_id,
        process_nonce="proc-1",
        calls=observations,
        call_count=calls,
        sealed=sealed,
    )


def _submission(segment: AccountingSegmentV1) -> SegmentSubmissionV1:
    from app.models.shared.llm_accounting import canonical_accounting_hash

    return SegmentSubmissionV1(
        segment=segment,
        payload_hash=canonical_accounting_hash(segment.stable_payload()),
    )


def test_memory_duplicate_is_noop_and_conflict_keeps_first():
    repo = MemoryLLMAccountingRepository()
    first = _submission(_segment())
    assert repo.save_segment(first) == "sealed"
    assert repo.save_segment(first) == "duplicate"
    conflicting = _submission(_segment(calls=2))
    assert repo.save_segment(conflicting) == "conflict"
    records = repo.get_task("learning_documents", "run-1")
    assert records.conflicts == 1
    assert len(records.calls) == 1


def test_sql_round_trip_and_idempotent_redelivery():
    tmp = tempfile.mkdtemp()
    try:
        repo = SQLLLMAccountingRepository(str(Path(tmp) / "accounting.db"))
        submission = _submission(_segment(calls=3))
        assert repo.save_segment(submission) == "sealed"
        assert repo.save_segment(submission) == "duplicate"
        records = repo.get_task("learning_documents", "run-1")
        assert len(records.calls) == 3
        assert records.segments and records.segments[0].sealed
        assert all(isinstance(item, SegmentInfoV1) for item in records.segments)
        assert repo.purge_task("learning_documents", "run-1") == 1
        assert repo.get_task("learning_documents", "run-1").calls == []
        repo.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sql_conflicting_primary_key_keeps_first_value():
    tmp = tempfile.mkdtemp()
    try:
        repo = SQLLLMAccountingRepository(str(Path(tmp) / "accounting.db"))
        repo.save_segment(_submission(_segment()))
        repo.save_segment(_submission(_segment(calls=2)))
        records = repo.get_task("learning_documents", "run-1")
        assert records.conflicts == 1
        assert len(records.calls) == 1
        repo.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_sql_readonly_never_creates_tables():
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / "fresh.db"
        repo = SQLLLMAccountingRepository(str(db_path), readonly=True)
        assert not db_path.exists() or not _has_tables(repo)
        records = repo.get_task("learning_documents", "run-x")
        assert records.unavailable_reasons
        repo.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _has_tables(repo) -> bool:
    from sqlalchemy import inspect

    inspector = inspect(repo.engine)
    return inspector.has_table("llm_call_observations")


def test_business_tables_untouched_by_accounting_writes():
    tmp = tempfile.mkdtemp()
    try:
        repo = SQLLLMAccountingRepository(str(Path(tmp) / "accounting.db"))
        repo.save_segment(_submission(_segment()))
        from sqlalchemy import inspect

        inspector = inspect(repo.engine)
        tables = set(inspector.get_table_names())
        assert "llm_call_observations" in tables
        assert "llm_accounting_segments" in tables
        # No business table is created or registered by the accounting store.
        assert not (tables & {"agent_runs", "agent_steps", "courseware_generation_jobs"})
        repo.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_more_than_ten_calls_are_all_persisted():
    tmp = tempfile.mkdtemp()
    try:
        repo = SQLLLMAccountingRepository(str(Path(tmp) / "accounting.db"))
        repo.save_segment(_submission(_segment(calls=25)))
        records = repo.get_task("learning_documents", "run-1")
        assert len(records.calls) == 25
        repo.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
