"""In-memory accounting repository with SQL-equivalent semantics."""

from __future__ import annotations

from app.db.audit.llm_accounting.base import TaskAccountingRecords
from app.models.shared.llm_accounting import (
    LLMCallObservationV1,
    SegmentInfoV1,
    SegmentSubmissionV1,
    canonical_accounting_hash,
)


class MemoryLLMAccountingRepository:
    """Same dedup/conflict semantics as the SQL repository, no persistence."""

    def __init__(self) -> None:
        self._calls: dict[tuple[str, str, str, int], dict] = {}
        self._segments: dict[tuple[str, str, str], dict] = {}

    def save_segment(self, submission: SegmentSubmissionV1) -> str:
        segment = submission.segment
        key = (segment.domain, segment.run_id, segment.segment_id)
        if key in self._segments:
            existing = self._segments[key]
            if existing["manifest_hash"] == submission.payload_hash:
                return "duplicate"
            existing["received_status"] = "conflict"
            return "conflict"
        self._segments[key] = {
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
        for call in segment.calls:
            call_key = call.observation_key()
            if call_key in self._calls:
                existing_call = self._calls[call_key]
                if existing_call["payload_hash"] == canonical_accounting_hash(
                    call.stable_payload()
                ):
                    continue
                self._segments[key]["received_status"] = "conflict"
                continue
            self._calls[call_key] = {
                "payload_json": call.model_dump_json(),
                "payload_hash": canonical_accounting_hash(call.stable_payload()),
                "recorded_at": call.recorded_at,
            }
        return "sealed" if segment.sealed else "partial"

    def get_task(self, domain: str, run_id: str) -> TaskAccountingRecords:
        records = TaskAccountingRecords()
        for key in sorted(self._segments, key=lambda k: (k[0], k[1], k[2])):
            if key[0] != domain or key[1] != run_id:
                continue
            row = self._segments[key]
            records.segments.append(
                SegmentInfoV1(
                    segment_id=key[2],
                    recorded_at=row["recorded_at"],
                    call_count=row["expected_calls"],
                    sealed=row["received_status"] == "sealed",
                    incomplete_reasons=[],
                    capacity_exceeded=False,
                )
            )
            if row["received_status"] == "conflict":
                records.conflicts += 1
        for key in sorted(self._calls, key=lambda k: (k[0], k[1], k[2], k[3])):
            if key[0] != domain or key[1] != run_id:
                continue
            records.calls.append(
                LLMCallObservationV1.model_validate_json(self._calls[key]["payload_json"])
            )
        return records

    def purge_task(self, domain: str, run_id: str) -> int:
        removed = 0
        for key in [k for k in self._segments if k[0] == domain and k[1] == run_id]:
            del self._segments[key]
            removed += 1
        for key in [k for k in self._calls if k[0] == domain and k[1] == run_id]:
            del self._calls[key]
        return removed

    def close(self) -> None:
        return None
