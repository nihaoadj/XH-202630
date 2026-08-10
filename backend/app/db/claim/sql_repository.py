from __future__ import annotations

import hashlib
from collections.abc import Callable

from sqlalchemy.orm import Session

from app.db.audit.base import PersistenceConflict
from app.db.claim.base import BaseClaimRepository
from app.db.models import (
    ClaimEvidenceORM,
    ClaimJudgementORM,
    ResourceClaimORM,
    ResourceReviewORM,
    RetrievalEvidenceSnapshotORM,
)
from app.models.claims import ClaimJudgement, ClaimRecord


class SQLClaimRepository(BaseClaimRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def save_audit(self, claims: list[ClaimRecord], judgements: list[ClaimJudgement]) -> None:
        claims_by_id = {item.claim_id: item for item in claims}
        if any(item.claim_id not in claims_by_id for item in judgements):
            raise PersistenceConflict("judgement references claim outside batch")
        evidence_ids = {evidence_id for item in judgements for evidence_id in item.evidence_ids}
        with self.session_factory() as db:
            snapshots = {
                row.evidence_id: row
                for row in db.query(RetrievalEvidenceSnapshotORM)
                .filter(RetrievalEvidenceSnapshotORM.evidence_id.in_(evidence_ids or {""}))
                .all()
            }
            if set(snapshots) != evidence_ids:
                raise PersistenceConflict("claim judgement references missing frozen evidence")
            for item in judgements:
                if any(snapshots[evidence_id].run_id != item.run_id for evidence_id in item.evidence_ids):
                    raise PersistenceConflict("claim evidence crosses run boundary")
            for claim in claims:
                existing = db.get(ResourceClaimORM, claim.claim_id)
                if existing:
                    if existing.claim_hash != claim.claim_hash:
                        raise PersistenceConflict("claim immutable payload conflict")
                    continue
                judgement = next(item for item in judgements if item.claim_id == claim.claim_id)
                db.add(ResourceClaimORM(
                    claim_id=claim.claim_id,
                    review_id=claim.review_id,
                    resource_id=claim.resource_id,
                    schema_version=claim.schema_version,
                    run_id=claim.run_id,
                    resource_version=claim.resource_version,
                    claim_index=claim.claim_index,
                    claim_type=claim.claim_type.value,
                    knowledge_point=claim.knowledge_point_id,
                    knowledge_point_id=claim.knowledge_point_id,
                    claim_text=claim.claim_text,
                    source_text=claim.source_text,
                    source_start=claim.source_start,
                    source_end=claim.source_end,
                    source_text_hash=claim.source_text_hash,
                    extraction_method=claim.extraction_method,
                    extractor_model=claim.extractor_model,
                    extractor_prompt_version=claim.extractor_prompt_version,
                    claim_hash=claim.claim_hash,
                    supported=judgement.verdict == "supported",
                    confidence=judgement.confidence,
                    evidence_refs=claim.source_evidence_ids,
                    created_at=claim.created_at,
                ))
            db.flush()
            for item in judgements:
                existing = db.get(ClaimJudgementORM, item.judgement_id)
                if existing:
                    if existing.claim_id != item.claim_id or existing.verdict != (item.verdict.value if item.verdict else None):
                        raise PersistenceConflict("judgement immutable payload conflict")
                    continue
                db.add(ClaimJudgementORM(
                    judgement_id=item.judgement_id,
                    claim_id=item.claim_id,
                    run_id=item.run_id,
                    resource_id=item.resource_id,
                    resource_version=item.resource_version,
                    review_id=item.review_id,
                    status=item.status.value,
                    verdict=item.verdict.value if item.verdict else None,
                    reason=item.reason,
                    judge_type=item.judge_type.value,
                    judge_model=item.judge_model,
                    judge_prompt_version=item.judge_prompt_version,
                    confidence=item.confidence,
                    created_at=item.created_at,
                ))
                for evidence_id in item.evidence_ids:
                    digest = hashlib.sha256(f"{item.judgement_id}\x1f{evidence_id}".encode()).hexdigest()[:32]
                    db.add(ClaimEvidenceORM(
                        binding_id=f"cev_{digest}",
                        judgement_id=item.judgement_id,
                        claim_id=item.claim_id,
                        evidence_id=evidence_id,
                        run_id=item.run_id,
                    ))
            for resource_id in {item.resource_id for item in claims}:
                resource_claims = [item for item in claims if item.resource_id == resource_id]
                resource_judgements = [item for item in judgements if item.resource_id == resource_id]
                factual_ids = {item.claim_id for item in resource_claims if item.claim_type.value == "factual"}
                completed = {item.claim_id: item for item in resource_judgements if item.status.value == "completed"}
                incomplete = len(factual_ids - set(completed))
                supported = sum(completed[item].verdict.value == "supported" for item in factual_ids if item in completed)
                contradicted = sum(completed[item].verdict.value == "contradicted" for item in factual_ids if item in completed)
                absent = sum(completed[item].verdict.value == "not_in_evidence" for item in factual_ids if item in completed)
                metric_status = "incomplete" if incomplete else "not_applicable" if not factual_ids else "complete"
                rate = None if incomplete else ((contradicted + absent) / len(factual_ids) if factual_ids else 0.0)
                for review_id in {item.review_id for item in resource_claims}:
                    review = db.get(ResourceReviewORM, review_id)
                    if review is not None:
                        review.claim_total = len(resource_claims)
                        review.claim_supported = supported
                        review.claim_unsupported = contradicted + absent
                        review.suspected_hallucinations = contradicted + absent
                        review.claim_hallucination_rate = rate
                        review.claim_metric_status = metric_status
            db.commit()

    @staticmethod
    def _claim(row: ResourceClaimORM) -> ClaimRecord:
        return ClaimRecord(
            schema_version="2.0",
            claim_id=row.claim_id,
            run_id=row.run_id,
            resource_id=row.resource_id,
            resource_version=row.resource_version,
            review_id=row.review_id,
            claim_index=row.claim_index,
            claim_text=row.claim_text,
            claim_type=row.claim_type,
            source_text=row.source_text,
            source_start=row.source_start,
            source_end=row.source_end,
            source_text_hash=row.source_text_hash,
            knowledge_point_id=row.knowledge_point_id,
            source_evidence_ids=list(row.evidence_refs or []),
            extraction_method=row.extraction_method,
            extractor_model=row.extractor_model,
            extractor_prompt_version=row.extractor_prompt_version,
            claim_hash=row.claim_hash,
            created_at=row.created_at,
        )

    def list_claims_by_run(self, run_id: str) -> list[ClaimRecord]:
        with self.session_factory() as db:
            rows = db.query(ResourceClaimORM).filter_by(run_id=run_id, schema_version="2.0").order_by(
                ResourceClaimORM.resource_id, ResourceClaimORM.resource_version, ResourceClaimORM.claim_index
            ).all()
            return [self._claim(row) for row in rows]

    def list_judgements_by_run(self, run_id: str) -> list[ClaimJudgement]:
        with self.session_factory() as db:
            rows = db.query(ClaimJudgementORM).filter_by(run_id=run_id).order_by(
                ClaimJudgementORM.resource_id, ClaimJudgementORM.resource_version, ClaimJudgementORM.claim_id
            ).all()
            evidence = db.query(ClaimEvidenceORM).filter_by(run_id=run_id).all()
            by_judgement: dict[str, list[str]] = {}
            for item in evidence:
                by_judgement.setdefault(item.judgement_id, []).append(item.evidence_id)
            return [ClaimJudgement(
                judgement_id=row.judgement_id,
                claim_id=row.claim_id,
                run_id=row.run_id,
                resource_id=row.resource_id,
                resource_version=row.resource_version,
                review_id=row.review_id,
                status=row.status,
                verdict=row.verdict,
                evidence_ids=sorted(by_judgement.get(row.judgement_id, [])),
                reason=row.reason,
                judge_type=row.judge_type,
                judge_model=row.judge_model,
                judge_prompt_version=row.judge_prompt_version,
                confidence=row.confidence,
                created_at=row.created_at,
            ) for row in rows]
