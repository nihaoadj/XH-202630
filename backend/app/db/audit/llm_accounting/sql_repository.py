"""SQLite repository for the independent LLM-call accounting database.

The engine is private to this store (never the business engine), uses a zero
busy timeout so a locked accounting file never waits on business locks, and
checks a bounded total-size guard before writing.
"""

from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from sqlalchemy import create_engine, delete, insert, select
from sqlalchemy.engine import Engine

from app.db.audit.llm_accounting.base import TaskAccountingRecords
from app.db.audit.llm_accounting.migrations import ensure_schema
from app.db.audit.llm_accounting.schema import (
    llm_accounting_segments,
    llm_call_observations,
)
from app.models.shared.llm_accounting import (
    AccountingSegmentV1,
    LLM_ACCOUNTING_SCHEMA_VERSION,
    LLMCallObservationV1,
    SegmentInfoV1,
    SegmentSubmissionV1,
    canonical_accounting_hash,
)

logger = logging.getLogger(__name__)

# 256 MiB hard capacity guard for the accounting database (T41 §6.2).
MAX_ACCOUNTING_DB_BYTES = 256 * 1024 * 1024


class SQLLLMAccountingRepository:
    """Persist sealed segment snapshots in short independent transactions."""

    def __init__(self, path: str, *, max_bytes: int = MAX_ACCOUNTING_DB_BYTES, readonly: bool = False):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.readonly = readonly
        self.engine = None
        self.storage_capacity_exceeded = False
        if readonly and not self.path.is_file():
            self.storage_capacity_exceeded = True
            return
        if not readonly:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        uri_path = quote(self.path.resolve().as_posix(), safe="/:")
        url = f"sqlite:///file:{uri_path}?mode=ro&uri=true" if readonly else f"sqlite:///{self.path}"
        self.engine: Engine = create_engine(
            url,
            connect_args={"timeout": 0},
        )
        self.storage_capacity_exceeded = False
        if self.readonly:
            # Query paths must never create tables (T41 §7).
            try:
                from sqlalchemy import inspect as _inspect

                inspector = _inspect(self.engine)
                for table in (llm_call_observations, llm_accounting_segments):
                    if not inspector.has_table(table.name):
                        self.storage_capacity_exceeded = True
            except Exception:
                self.storage_capacity_exceeded = True
        else:
            try:
                # Only this independent store uses WAL: readers must not make
                # the zero-wait writer drop records through a shared read lock.
                with self.engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                    connection.commit()
                ensure_schema(self.engine)
            except Exception:
                logger.warning("llm-accounting schema initialization failed path=%s", self.path.name)
                self.storage_capacity_exceeded = True

    # -- helpers -----------------------------------------------------------
    def _db_size_bytes(self) -> int:
        try:
            return sum(p.stat().st_size for p in (
                self.path, Path(str(self.path) + "-wal"), Path(str(self.path) + "-shm"),
            ) if p.exists())
        except OSError:
            return 0

    def _segment_row(self, submission: SegmentSubmissionV1) -> dict:
        segment = submission.segment
        return {
            "domain": segment.domain,
            "run_id": segment.run_id,
            "segment_id": segment.segment_id,
            "manifest_json": segment.model_dump_json(exclude={"calls"}),
            "manifest_hash": submission.payload_hash,
            "expected_calls": segment.call_count,
            "received_calls": segment.call_count,
            "received_status": "sealed" if segment.sealed else "partial",
            "recorded_at": segment.recorded_at,
        }

    # -- repository protocol -----------------------------------------------
    def save_segment(self, submission: SegmentSubmissionV1) -> str:
        if self.storage_capacity_exceeded:
            return "partial"
        try:
            row = self._segment_row(submission)
            calls = submission.segment.calls
            payload_upper = sum(len(call.model_dump_json()) for call in calls) + len(
                row["manifest_json"]
            )
            if self._db_size_bytes() + payload_upper > self.max_bytes:
                self.storage_capacity_exceeded = True
                logger.warning("llm-accounting db capacity guard hit path=%s", self.path.name)
                return "partial"
            with self.engine.begin() as connection:
                existing = connection.execute(
                    select(llm_accounting_segments.c.manifest_hash).where(
                        llm_accounting_segments.c.domain == row["domain"],
                        llm_accounting_segments.c.run_id == row["run_id"],
                        llm_accounting_segments.c.segment_id == row["segment_id"],
                    )
                ).first()
                if existing is not None:
                    if existing[0] == row["manifest_hash"]:
                        return "duplicate"
                    connection.execute(
                        llm_accounting_segments.update()
                        .where(
                            llm_accounting_segments.c.domain == row["domain"],
                            llm_accounting_segments.c.run_id == row["run_id"],
                            llm_accounting_segments.c.segment_id == row["segment_id"],
                        )
                        .values(received_status="conflict")
                    )
                    return "conflict"
                connection.execute(insert(llm_accounting_segments).values(row))
                for call in calls:
                    call_row = {
                        "domain": call.domain,
                        "run_id": call.run_id,
                        "segment_id": call.segment_id,
                        "observation_id": call.observation_id,
                        "stage": call.stage,
                        "step_id": call.step_id,
                        "source_call_id": call.source_call_id,
                        "payload_json": call.model_dump_json(),
                        "payload_hash": canonical_accounting_hash(call.stable_payload()),
                        "recorded_at": call.recorded_at,
                    }
                    existing_call = connection.execute(
                        select(llm_call_observations.c.payload_hash).where(
                            llm_call_observations.c.domain == call.domain,
                            llm_call_observations.c.run_id == call.run_id,
                            llm_call_observations.c.segment_id == call.segment_id,
                            llm_call_observations.c.observation_id == call.observation_id,
                        )
                    ).first()
                    if existing_call is not None:
                        if existing_call[0] != call_row["payload_hash"]:
                            connection.execute(
                                llm_accounting_segments.update()
                                .where(
                                    llm_accounting_segments.c.domain == call.domain,
                                    llm_accounting_segments.c.run_id == call.run_id,
                                    llm_accounting_segments.c.segment_id == call.segment_id,
                                )
                                .values(received_status="conflict")
                            )
                        continue
                    connection.execute(insert(llm_call_observations).values(call_row))
            return "sealed" if submission.segment.sealed else "partial"
        except Exception:
            logger.warning("llm-accounting segment save failed type=storage_write")
            return "partial"

    def get_task(self, domain: str, run_id: str) -> TaskAccountingRecords:
        records = TaskAccountingRecords()
        if self.readonly and self.storage_capacity_exceeded and self.path.is_file():
            # A reader may precede the asynchronous writer. Retry only readonly
            # inspection when the file appears; never create a missing store.
            self.close()
            self.__init__(str(self.path), max_bytes=self.max_bytes, readonly=True)
        if self.storage_capacity_exceeded and self.readonly:
            records.unavailable_reasons.append("storage_unavailable")
            return records
        try:
            with self.engine.connect() as connection:
                segment_rows = connection.execute(
                    select(
                        llm_accounting_segments.c.segment_id,
                        llm_accounting_segments.c.recorded_at,
                        llm_accounting_segments.c.expected_calls,
                        llm_accounting_segments.c.received_status,
                        llm_accounting_segments.c.manifest_json,
                        llm_accounting_segments.c.manifest_hash,
                    )
                    .where(
                        llm_accounting_segments.c.domain == domain,
                        llm_accounting_segments.c.run_id == run_id,
                    )
                    .order_by(
                        llm_accounting_segments.c.recorded_at,
                        llm_accounting_segments.c.segment_id,
                    )
                ).fetchall()
                for segment_id, recorded_at, expected_calls, status, _, _ in segment_rows:
                    records.segments.append(
                        SegmentInfoV1(
                            segment_id=segment_id,
                            recorded_at=recorded_at,
                            call_count=expected_calls,
                            sealed=status == "sealed",
                        )
                    )
                    if status == "conflict":
                        records.conflicts += 1
                call_rows = connection.execute(
                    select(llm_call_observations.c.payload_json, llm_call_observations.c.payload_hash)
                    .where(
                        llm_call_observations.c.domain == domain,
                        llm_call_observations.c.run_id == run_id,
                    )
                    .order_by(
                        llm_call_observations.c.segment_id,
                        llm_call_observations.c.observation_id,
                    )
                ).fetchall()
                for payload_json, digest in call_rows:
                    call = LLMCallObservationV1.model_validate_json(payload_json)
                    if (call.schema_version != LLM_ACCOUNTING_SCHEMA_VERSION
                            or call.domain != domain or call.run_id != run_id
                            or canonical_accounting_hash(call.stable_payload()) != digest):
                        raise ValueError("accounting payload integrity")
                    records.calls.append(call)
                for segment_id, _, count, _, manifest, digest in segment_rows:
                    segment = AccountingSegmentV1.model_validate_json(manifest)
                    segment.calls = [c for c in records.calls if c.segment_id == segment_id]
                    if (segment.schema_version != LLM_ACCOUNTING_SCHEMA_VERSION
                            or segment.domain != domain or segment.run_id != run_id
                            or len(segment.calls) != count
                            or canonical_accounting_hash(segment.stable_payload()) != digest):
                        raise ValueError("accounting manifest integrity")
        except Exception:
            logger.warning("llm-accounting task read failed type=storage_read")
            records.calls.clear()
            records.segments.clear()
            records.unavailable_reasons.append("storage_read_failed")
        return records

    def purge_task(self, domain: str, run_id: str) -> int:
        try:
            with self.engine.begin() as connection:
                connection.execute(
                    delete(llm_call_observations).where(
                        llm_call_observations.c.domain == domain,
                        llm_call_observations.c.run_id == run_id,
                    )
                )
                removed = connection.execute(
                    delete(llm_accounting_segments).where(
                        llm_accounting_segments.c.domain == domain,
                        llm_accounting_segments.c.run_id == run_id,
                    )
                ).rowcount
            return int(removed or 0)
        except Exception:
            logger.warning("llm-accounting purge failed type=storage_write")
            return 0

    def close(self) -> None:
        try:
            self.engine.dispose()
        except Exception:
            pass
