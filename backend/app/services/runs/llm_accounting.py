"""Read-only query service for task-level LLM-call accounting (T41 §7).

The service never writes: no table creation, no business writes, no history
recomputation.  Business existence/visibility is verified by the existing
domain services before these methods run; unknown business tasks are handled
by the API layer with the existing 404 semantics.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from app.db.audit.llm_accounting.base import TaskAccountingRecords
from app.models.shared.llm_accounting import (
    LLMCallObservationV1,
    SegmentInfoV1,
    TaskLLMAccountingResponseV1,
    build_task_response,
    deduplicate_observations,
)

logger = logging.getLogger(__name__)

DEFAULT_PAGE_LIMIT = 20
MAX_PAGE_LIMIT = 100


def encode_cursor(recorded_at: str, segment_id: str) -> str:
    payload = json.dumps([recorded_at, segment_id], ensure_ascii=False)
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str) -> tuple[str, str] | None:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
        if isinstance(payload, list) and len(payload) == 2:
            return str(payload[0]), str(payload[1])
    except Exception:
        return None
    return None


class LLMAccountingQueryService:
    """Aggregate persisted accounting rows for one task identity."""

    def __init__(self, db_path: str | None):
        self._db_path = db_path
        self._repository = None
        self._repository_failed = False

    def _records(self, domain: str, run_id: str) -> TaskAccountingRecords:
        if self._db_path is None or self._repository_failed:
            records = TaskAccountingRecords()
            records.unavailable_reasons.append("accounting_disabled")
            return records
        if not Path(self._db_path).is_file():
            records = TaskAccountingRecords()
            records.unavailable_reasons.append("storage_unavailable")
            return records
        if self._repository is None:
            try:
                from app.db.audit.llm_accounting.sql_repository import (
                    SQLLLMAccountingRepository,
                )

                self._repository = SQLLLMAccountingRepository(self._db_path, readonly=True)
            except Exception:
                self._repository_failed = True
                records = TaskAccountingRecords()
                records.unavailable_reasons.append("storage_unavailable")
                return records
        try:
            return self._repository.get_task(domain, run_id)
        except Exception:
            records = TaskAccountingRecords()
            records.unavailable_reasons.append("storage_read_failed")
            return records

    def query_task(
        self,
        *,
        domain: str,
        run_id: str,
        include_calls: bool = False,
        stage: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
        task_terminal: bool = False,
        expected_llm_stages: set[str] | None = None,
    ) -> TaskLLMAccountingResponseV1:
        """Build one task-level accounting response from persisted rows."""

        limit = max(1, min(int(limit), MAX_PAGE_LIMIT))
        records = self._records(domain, run_id)
        calls, conflicts = deduplicate_observations(records.calls)

        segments = list(records.segments)
        segments.sort(key=lambda item: (item.recorded_at, item.segment_id))

        reasons: list[str] = []
        if records.unavailable_reasons:
            availability = "unavailable"
            reasons.extend(records.unavailable_reasons)
        elif not segments and not calls:
            availability = "pending" if not task_terminal else "not_recorded"
        else:
            availability = "available"
            if conflicts:
                availability = "partial"
            if any(not item.sealed for item in segments):
                availability = "partial"
            if any(item.incomplete_reasons for item in segments):
                availability = "partial"

        if any(item.capacity_exceeded for item in segments):
            reasons.append("capacity_exceeded")

        # Composite cursor pagination over (recorded_at, segment_id).
        after = decode_cursor(cursor) if cursor else None
        if cursor and after is None:
            reasons.append("invalid_cursor")
        page = [
            item
            for item in segments
            if after is None or (item.recorded_at, item.segment_id) > after
        ]
        page = page[:limit]
        next_cursor = None
        has_more = False
        if page and len(page) == limit:
            last = page[-1]
            remaining = any(
                (item.recorded_at, item.segment_id) > (last.recorded_at, last.segment_id)
                for item in segments
            )
            if remaining:
                next_cursor = encode_cursor(last.recorded_at, last.segment_id)
                has_more = True

        page_segment_ids = {item.segment_id for item in page}
        page_calls = [call for call in calls if call.segment_id in page_segment_ids]
        if stage is not None:
            page_calls = [call for call in page_calls if call.stage == stage]

        coverage_complete = False
        coverage_reasons: list[str] = []
        if availability == "available" and task_terminal:
            if conflicts or any(not item.sealed for item in segments):
                coverage_reasons.append("incomplete_persistence")
            if any(
                not (call.capture_complete and call.attempt_complete and call.attribution_complete)
                for call in calls
            ):
                coverage_reasons.append("incomplete_capture")
            observed_stages = {call.stage or "unknown" for call in calls}
            if expected_llm_stages is None:
                coverage_reasons.append("unproven_execution_coverage")
            else:
                missing = set(expected_llm_stages) - observed_stages
                if missing:
                    coverage_reasons.append("missing_stage_observations")
            if not coverage_reasons:
                coverage_complete = True
        else:
            coverage_reasons.append("task_not_terminal_or_partial")

        response = build_task_response(
            domain=domain,
            run_id=run_id,
            observations=calls,
            segments=page,
            availability=availability,
            coverage_complete=coverage_complete,
            incomplete_reasons=list(reasons + coverage_reasons),
            include_calls=include_calls,
            stage_filter=stage,
            next_cursor=next_cursor,
            has_more=has_more,
            as_of=datetime.now(timezone.utc).isoformat(),
            conflicts=conflicts,
        )
        # Calls belong to the current page only (stage filter applied).
        if include_calls:
            response.calls = page_calls
        return response


__all__ = ["LLMAccountingQueryService", "encode_cursor", "decode_cursor"]
