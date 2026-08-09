"""Read-only, cross-process reconstruction of persisted workflow timelines."""

from __future__ import annotations

from app.core.errors import ApplicationError, ErrorCode
from app.db.audit.base import BaseAuditRepository
from app.db.resource.base import BaseResourceRepository
from app.models.persistence import (
    AgentRunRecord,
    PersistedEvidenceSnapshot,
    RunTimeline,
    RunSummary,
    WorkflowCheckpointSummary,
)


class RunQueryService:
    def __init__(
        self,
        repository: BaseAuditRepository,
        resource_repository: BaseResourceRepository | None = None,
    ):
        self.repository = repository
        self.resource_repository = resource_repository

    def get_run(self, run_id: str) -> AgentRunRecord:
        run = self.repository.get_run(run_id)
        if run is None:
            raise ApplicationError(ErrorCode.WORKFLOW_RUN_NOT_FOUND, status_code=404)
        return run

    def get_summary(self, run_id: str) -> RunSummary:
        return RunSummary.from_record(self.get_run(run_id))

    def get_timeline(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 100,
    ) -> RunTimeline:
        run = self.get_run(run_id)
        try:
            events = self.repository.list_events(
                run_id,
                after_sequence=after_sequence,
                limit=limit + 1,
            )
            has_more = len(events) > limit
            page = events[:limit]
            checkpoints = self.repository.list_checkpoints(run_id)
        except ValueError as exc:
            raise ApplicationError(ErrorCode.WORKFLOW_CHECKPOINT_INVALID, status_code=409) from exc
        try:
            evidence = self.repository.list_evidence(run_id)
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.WORKFLOW_EVIDENCE_SNAPSHOT_CONFLICT,
                status_code=409,
            ) from exc
        return RunTimeline(
            run=RunSummary.from_record(run),
            steps=self.repository.list_steps(run_id),
            events=page,
            checkpoints=[
                WorkflowCheckpointSummary(
                    checkpoint_id=item.checkpoint_id,
                    event_sequence=item.event_sequence,
                    step_id=item.step_id,
                    step_sequence=item.step_sequence,
                    node_name=item.node_name,
                    state_hash=item.state_hash,
                    created_at=item.created_at,
                )
                for item in checkpoints
            ],
            evidence=evidence,
            resource_versions=(
                [resource.model_dump(mode="json") for resource in self.resource_repository.list_by_run(run_id)]
                if self.resource_repository is not None
                else []
            ),
            reviews=self.repository.list_reviews_by_run(run_id),
            replay_completeness=run.replay_completeness,
            next_event_sequence=page[-1].event_sequence if has_more and page else None,
        )

    def get_evidence(self, run_id: str) -> list[PersistedEvidenceSnapshot]:
        self.get_run(run_id)
        try:
            return self.repository.list_evidence(run_id)
        except ValueError as exc:
            raise ApplicationError(
                ErrorCode.WORKFLOW_EVIDENCE_SNAPSHOT_CONFLICT,
                status_code=409,
            ) from exc
