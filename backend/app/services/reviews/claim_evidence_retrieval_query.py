"""Read-only projection of the optional Claim evidence retrieval feature.

The service never starts work: it only reads committed sessions, scopes and
round-1 judgements.  Detailed Claim and evidence bodies stay on the existing
authorised review-detail endpoints.
"""

from __future__ import annotations

from typing import Sequence

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.nodes import (
    claim_evidence_summary,
)
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalStatus,
    ClaimEvidenceRetrievalSummaryV1,
)


class ClaimEvidenceRetrievalNotFound(ApplicationError):
    def __init__(self) -> None:
        super().__init__(ErrorCode.WORKFLOW_RUN_NOT_FOUND, status_code=404)


class ClaimEvidenceRetrievalQueryService:
    def __init__(
        self,
        *,
        audit_repository,
        claim_repository,
        supplement_repository=None,
        generation_job_repository=None,
    ):
        self.audit_repository = audit_repository
        self.claim_repository = claim_repository
        self.supplement_repository = supplement_repository
        self.generation_job_repository = generation_job_repository

    def _requested(self, run_id: str) -> bool:
        if self.generation_job_repository is not None:
            try:
                job = self.generation_job_repository.get(run_id)
            except Exception:  # noqa: BLE001 - read-only projection
                job = None
            payload = getattr(job, "request_payload", None) if job is not None else None
            if isinstance(payload, dict) and isinstance(
                payload.get("include_claim_evidence_retrieval"), bool,
            ):
                return payload["include_claim_evidence_retrieval"]
        try:
            checkpoints = self.audit_repository.list_checkpoints(run_id)
        except Exception:  # noqa: BLE001
            return False
        projection = checkpoints[-1].state_projection if checkpoints else {}
        if isinstance(projection.get("include_claim_evidence_retrieval"), bool):
            return projection["include_claim_evidence_retrieval"]
        if projection.get("claim_evidence_retrieval_policy"):
            return True
        # Before the first checkpoint the run creation snapshot is the durable
        # record of what was requested.
        try:
            creation = self.audit_repository.get_run_creation_snapshot(run_id)
        except Exception:  # noqa: BLE001 - read-only projection
            return False
        if isinstance(creation.get("include_claim_evidence_retrieval"), bool):
            return creation["include_claim_evidence_retrieval"]
        return bool(creation.get("claim_evidence_retrieval_policy"))

    def get(
        self, run_id: str, *, resource_id: str | None = None,
    ) -> ClaimEvidenceRetrievalSummaryV1:
        try:
            run = self.audit_repository.get_run(run_id)
        except Exception as exc:  # noqa: BLE001 - uniform 404 for unreadable runs
            raise ClaimEvidenceRetrievalNotFound() from exc
        if run is None:
            raise ClaimEvidenceRetrievalNotFound()
        claims = self.claim_repository.list_claims_by_run(run_id)
        judgements = self.claim_repository.list_judgements_by_run(run_id)
        sessions: Sequence = ()
        supplements: Sequence = ()
        if self.supplement_repository is not None:
            sessions = self.supplement_repository.list_sessions([run_id])
            supplements = self.supplement_repository.list_supplements([run_id])
        summary = claim_evidence_summary(
            run_id=run_id,
            claims=claims,
            round0=judgements,
            sessions=sessions,
            supplements=supplements,
            requested=self._requested(run_id),
            resource_id=resource_id,
        )
        if resource_id is not None and not summary.sessions and not summary.requested:
            raise ClaimEvidenceRetrievalNotFound()
        return summary


def empty_summary(run_id: str) -> ClaimEvidenceRetrievalSummaryV1:
    return ClaimEvidenceRetrievalSummaryV1(
        run_id=run_id,
        requested=False,
        status=ClaimEvidenceRetrievalStatus.NOT_REQUESTED,
    )


__all__ = [
    "ClaimEvidenceRetrievalNotFound",
    "ClaimEvidenceRetrievalQueryService",
    "empty_summary",
]
