"""Read-only, cross-process reconstruction of persisted workflow timelines."""

from __future__ import annotations

from app.core.errors import ApplicationError, ErrorCode
from app.db.audit.base import BaseAuditRepository
from app.db.resource.base import BaseResourceRepository
from app.db.claim.base import BaseClaimRepository
from app.db.feedback_loop.base import BaseFeedbackLoopRepository
from app.models.claims import ClaimMetricStatus, RunClaimsResponse, compute_claim_metric
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
        claim_repository: BaseClaimRepository | None = None,
        feedback_loop_repository: BaseFeedbackLoopRepository | None = None,
    ):
        self.repository = repository
        self.resource_repository = resource_repository
        self.claim_repository = claim_repository
        self.feedback_loop_repository = feedback_loop_repository

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
            trigger_relation=(
                self.feedback_loop_repository.get_followup_relation(run_id)
                if self.feedback_loop_repository is not None
                else None
            ),
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

    def get_claims(self, run_id: str) -> RunClaimsResponse:
        self.get_run(run_id)
        if self.claim_repository is None:
            return RunClaimsResponse(run_id=run_id)
        claims = self.claim_repository.list_claims_by_run(run_id)
        judgements = self.claim_repository.list_judgements_by_run(run_id)
        if not claims:
            return RunClaimsResponse(run_id=run_id)
        resource_ids = sorted({item.resource_id for item in claims})
        metrics = {
            resource_id: compute_claim_metric(
                [item for item in claims if item.resource_id == resource_id],
                [item for item in judgements if item.resource_id == resource_id],
            )
            for resource_id in resource_ids
        }
        audit_status = (
            ClaimMetricStatus.INCOMPLETE
            if any(item.metric_status == ClaimMetricStatus.INCOMPLETE for item in metrics.values())
            else ClaimMetricStatus.COMPLETE
        )
        return RunClaimsResponse(
            run_id=run_id,
            audit_status=audit_status,
            claims=claims,
            judgements=judgements,
            resource_metrics=metrics,
        )
