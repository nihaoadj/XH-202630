"""Replay and live-tail the durable WorkflowEvent ledger over SSE."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from app.config import Settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.db.audit.base import BaseAuditRepository
from app.db.generation.base import BaseGenerationJobRepository
from app.models.shared.persistence import (
    TERMINAL_RUN_STATUSES,
    ReplayCompleteness,
    WorkflowEvent,
)
from app.models.shared.streaming import (
    PublicRunEvent,
    PublicRunSnapshot,
    PublicStreamError,
    PublicStreamPing,
)


_PUBLIC_PAYLOAD_KEYS = frozenset({
    "action",
    "attempt",
    "attempt_id",
    "candidate_count",
    "child_run_id",
    "claim_count",
    "claim_ids",
    "completed_node_ids",
    "count",
    "decision",
    "decision_id",
    "dropped_count",
    "duration_ms",
    "evidence_ids",
    "finalization_stage",
    "generation_attempt",
    "inserted_node_ids",
    "issue_count",
    "knowledge_point_ids",
    "mutation_id",
    "overall_score",
    "parent_resource_id",
    "resource_id",
    "path_id",
    "profile_version",
    "resource_ids",
    "resource_spec_id",
    "resource_family_id",
    "resource_type",
    "representation",
    "resource_execution_state",
    "agent_name",
    "prompt_version",
    "artifact_format",
    "validation_status",
    "publication_status",
    "review_id",
    "retry_count",
    "review_ids",
    "revision_count",
    "reason_codes",
    "safe_message",
    "unlocked_node_ids",
    "valid_evidence_count",
    "version",
})

_EVENT_SUMMARIES = {
    "run_created": "运行记录已创建",
    "run_started": "工作流已开始",
    "step_started": "Agent 步骤开始",
    "step_succeeded": "Agent 步骤完成",
    "step_degraded": "Agent 步骤降级完成",
    "step_failed": "Agent 步骤失败",
    "evidence_snapshot_saved": "检索证据快照已保存",
    "checkpoint_saved": "工作流检查点已保存",
    "resource_version_created": "资源版本已创建",
    "review_persisted": "审核结果已保存",
    "revision_requested": "已请求定向返工",
    "claim_extraction_started": "Claim 抽取开始",
    "claim_extraction_completed": "Claim 抽取完成",
    "claim_judgement_completed": "Claim 判定完成",
    "claim_review_failed": "Claim 审核未通过",
    "claim_metric_computed": "Claim 指标已计算",
    "resource_published": "资源已发布",
    "attempt_submitted": "学习 Attempt 已提交",
    "feedback_decision_completed": "反馈决策已完成",
    "knowledge_state_updated": "知识状态已更新",
    "profile_updated": "学习画像已更新",
    "path_mutated": "学习路径已变更",
    "followup_generation_created": "后续生成任务已创建",
    "followup_generation_failed": "后续生成任务创建失败",
    "run_finalizing": "工作流正在收尾",
    "run_completed": "工作流已完成",
    "run_failed": "工作流失败",
    "run_interrupted": "工作流已中断",
}


def _public_payload(event: WorkflowEvent) -> dict:
    """Project internal payloads through a second, scalar-only allow-list."""

    result = {}
    for key, value in event.payload.items():
        if key not in _PUBLIC_PAYLOAD_KEYS:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        elif isinstance(value, list):
            result[key] = [item for item in value if isinstance(item, (str, int, float, bool)) or item is None][:100]
    # Existing Claim events contain bounded nested counters. Flatten counts rather
    # than exposing the internal object or weakening the public DTO.
    verdict_counts = event.payload.get("verdict_counts")
    if isinstance(verdict_counts, dict):
        for verdict in ("supported", "contradicted", "not_in_evidence", "non_factual", "incomplete"):
            value = verdict_counts.get(verdict)
            if isinstance(value, int) and value >= 0:
                result[f"{verdict}_count"] = value
    resource_metrics = event.payload.get("resource_metrics")
    if isinstance(resource_metrics, dict):
        result["resource_metric_count"] = len(resource_metrics)
    return result


def to_public_event(event: WorkflowEvent) -> PublicRunEvent:
    return PublicRunEvent(
        run_id=event.run_id,
        event_id=event.event_id,
        sequence=event.event_sequence,
        event_type=event.event_type.value,
        step_id=event.step_id,
        step_sequence=event.step_sequence,
        node_name=event.node_name,
        status=event.status,
        summary=_EVENT_SUMMARIES.get(event.event_type.value, "工作流状态已更新"),
        payload=_public_payload(event),
        error_code=event.error_code,
        occurred_at=event.occurred_at,
    )


def _json_line(model) -> str:
    return json.dumps(model.model_dump(mode="json", exclude_none=True), ensure_ascii=False, separators=(",", ":"))


def snapshot_frame(snapshot: PublicRunSnapshot) -> str:
    return f"event: snapshot\ndata: {_json_line(snapshot)}\n\n"


def event_frame(event: PublicRunEvent) -> str:
    return f"id: {event.sequence}\nevent: {event.event_type}\ndata: {_json_line(event)}\n\n"


def ping_frame(ping: PublicStreamPing) -> str:
    return f"event: ping\ndata: {_json_line(ping)}\n\n"


def error_frame(error: PublicStreamError) -> str:
    return f"event: stream_error\ndata: {_json_line(error)}\n\n"


class RunEventStreamService:
    def __init__(
        self,
        repository: BaseAuditRepository,
        generation_job_repository: BaseGenerationJobRepository,
        settings: Settings,
    ) -> None:
        self.repository = repository
        self.generation_job_repository = generation_job_repository
        self.poll_interval = settings.workflow_sse_poll_interval_seconds
        self.heartbeat_interval = settings.workflow_sse_heartbeat_seconds
        self.page_size = settings.workflow_sse_event_page_size

    @staticmethod
    def resolve_cursor(last_event_id: str | None, after_sequence: str | int | None) -> int:
        def parse(value, source: str) -> int | None:
            if value is None or value == "":
                return None
            try:
                parsed = int(value)
            except (TypeError, ValueError):
                raise ApplicationError(ErrorCode.WORKFLOW_STREAM_CURSOR_INVALID, status_code=400) from None
            if parsed < 0:
                raise ApplicationError(ErrorCode.WORKFLOW_STREAM_CURSOR_INVALID, status_code=400)
            return parsed

        # Native EventSource reconnects the same URL and adds Last-Event-ID. The
        # URL may still contain its initial after_sequence, so the header has a
        # documented, deterministic priority instead of creating a false conflict.
        header_cursor = parse(last_event_id, "Last-Event-ID")
        if header_cursor is not None:
            return header_cursor
        return parse(after_sequence, "after_sequence") or 0

    def get_snapshot(self, run_id: str) -> PublicRunSnapshot:
        try:
            run = self.repository.get_run(run_id)
        except Exception:
            raise ApplicationError(ErrorCode.WORKFLOW_STREAM_UNAVAILABLE, status_code=503) from None
        try:
            job = self.generation_job_repository.get(run_id)
        except Exception:
            if run is None:
                raise ApplicationError(ErrorCode.WORKFLOW_STREAM_UNAVAILABLE, status_code=503) from None
            job = None
        if run is None and job is None:
            raise ApplicationError(ErrorCode.WORKFLOW_STREAM_RUN_NOT_FOUND, status_code=404)
        if run is None:
            return PublicRunSnapshot(
                run_id=run_id,
                job_status=job.job_status,
                updated_at=job.finished_at or job.started_at or job.created_at,
                is_terminal=job.job_status in {"completed", "failed"},
            )
        return PublicRunSnapshot(
            run_id=run_id,
            run_status=run.status,
            workflow_status=run.workflow_status,
            current_node=run.current_node,
            current_step_sequence=run.current_step_sequence,
            generation_attempt=run.generation_attempt,
            revision_count=run.revision_count,
            retrieval_status=run.retrieval_status,
            final_decision=run.final_decision,
            replay_completeness=run.replay_completeness,
            started_at=run.started_at,
            updated_at=run.updated_at,
            ended_at=run.ended_at,
            last_event_sequence=run.last_event_sequence,
            job_status=job.job_status if job else None,
            is_terminal=run.status in TERMINAL_RUN_STATUSES,
        )

    def validate_initial_cursor(self, snapshot: PublicRunSnapshot, cursor: int) -> None:
        if cursor > snapshot.last_event_sequence:
            raise ApplicationError(ErrorCode.WORKFLOW_STREAM_CURSOR_INVALID, status_code=400)

    async def prepare(self, run_id: str, cursor: int) -> PublicRunSnapshot:
        snapshot = await asyncio.to_thread(self.get_snapshot, run_id)
        self.validate_initial_cursor(snapshot, cursor)
        return snapshot

    async def stream(
        self,
        run_id: str,
        *,
        cursor: int,
        initial_snapshot: PublicRunSnapshot,
        is_disconnected: Callable[[], Awaitable[bool]] | None = None,
    ):
        """Send a snapshot, replay backlog, then live-tail short DB queries.

        Disconnect only stops this read loop; it never mutates the job or Run.
        """

        yield snapshot_frame(initial_snapshot)
        last_heartbeat = time.monotonic()
        while True:
            if is_disconnected is not None and await is_disconnected():
                return
            try:
                events = await asyncio.to_thread(
                    self.repository.list_events,
                    run_id,
                    after_sequence=cursor,
                    limit=self.page_size,
                )
                run = await asyncio.to_thread(self.repository.get_run, run_id)
                try:
                    job = await asyncio.to_thread(self.generation_job_repository.get, run_id)
                except Exception:
                    if run is None:
                        raise
                    job = None
            except asyncio.CancelledError:
                raise
            except Exception:
                error = PublicStreamError(
                    run_id=run_id,
                    code=ErrorCode.WORKFLOW_STREAM_UNAVAILABLE.value,
                    message="工作流事件流当前不可用",
                    last_event_sequence=cursor,
                )
                yield error_frame(error)
                return

            if events:
                for event in events:
                    expected = cursor + 1
                    legacy_partial = run is not None and run.replay_completeness == ReplayCompleteness.LEGACY_PARTIAL
                    if event.event_sequence != expected and not legacy_partial:
                        error = PublicStreamError(
                            run_id=run_id,
                            code=ErrorCode.WORKFLOW_STREAM_EVENT_SEQUENCE_INVALID.value,
                            message="工作流事件序列不完整",
                            last_event_sequence=cursor,
                        )
                        yield error_frame(error)
                        return
                    yield event_frame(to_public_event(event))
                    cursor = event.event_sequence
                # A full page means backlog may remain. Continue immediately instead
                # of sleeping or sending a heartbeat between replay pages.
                if len(events) >= self.page_size:
                    continue
                last_heartbeat = time.monotonic()

            run_terminal = run is not None and run.status in TERMINAL_RUN_STATUSES
            job_only_terminal = run is None and job is not None and job.job_status in {"completed", "failed"}
            last_sequence = run.last_event_sequence if run is not None else 0
            if (run_terminal and cursor >= last_sequence) or job_only_terminal:
                return

            now = time.monotonic()
            if now - last_heartbeat >= self.heartbeat_interval:
                yield ping_frame(PublicStreamPing(
                    run_id=run_id,
                    last_event_sequence=cursor,
                    server_time=datetime.now(timezone.utc),
                ))
                last_heartbeat = now
            await asyncio.sleep(self.poll_interval)
