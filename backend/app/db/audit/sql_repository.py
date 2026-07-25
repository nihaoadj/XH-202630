"""SQLAlchemy 实现的 Agent 运行与审核审计仓库。"""
from __future__ import annotations

import uuid
from typing import Any, Callable, Iterable, Optional

from sqlalchemy.orm import Session

from app.db.audit.base import BaseAuditRepository
from app.db.models import AgentRunORM, AgentStepORM, ResourceClaimORM, ResourceReviewORM
from app.models.schemas import ResourceClaim, ReviewSummary, SourceRef


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return dict(value)


class SQLAuditRepository(BaseAuditRepository):
    def __init__(self, session_factory: Callable[[], Session]):
        self.session_factory = session_factory

    def save_run(self, learner_id, knowledge_base_id, topic, trace: Iterable[dict[str, Any]], input_payload, output_payload, status):
        run_id = str(uuid.uuid4())
        steps = [_as_dict(item) for item in trace]
        with self.session_factory() as db:
            db.add(
                AgentRunORM(
                    run_id=run_id,
                    learner_id=learner_id,
                    knowledge_base_id=knowledge_base_id,
                    topic=topic,
                    status=status,
                    input_payload=input_payload,
                    output_payload=output_payload,
                )
            )
            for step_no, step in enumerate(steps, start=1):
                db.add(
                    AgentStepORM(
                        step_id=step.get("step_id") or f"{run_id}:{step_no}",
                        run_id=run_id,
                        step_no=step_no,
                        agent_name=step.get("agent_name", "unknown"),
                        action=step.get("action", "unknown"),
                        status=step.get("status", "success"),
                        input_payload=step.get("input_payload", {}),
                        output_payload=step.get("output_payload", {}),
                        decision_reason=step.get("decision_reason"),
                        evidence_refs=step.get("evidence_refs", []),
                        retry_count=step.get("retry_count", 0),
                        error_message=step.get("error_message"),
                        duration_ms=step.get("duration_ms"),
                    )
                )
            db.commit()
        return run_id

    def save_review(self, resource_id: str, review: dict[str, Any], run_id: Optional[str]) -> str:
        requested_id = review.get("review_id")
        review_id = f"{requested_id}:{resource_id}" if requested_id else str(uuid.uuid4())
        status = review.get("status") or ("passed" if review.get("passed") else "needs_review")
        claims = [_as_dict(claim) for claim in review.get("claims", [])]
        claim_total = review.get("claim_total", len(claims))
        claim_supported = review.get("claim_supported", sum(bool(claim.get("supported")) for claim in claims))
        claim_unsupported = review.get("claim_unsupported", max(0, claim_total - claim_supported))
        hallucination_rate = review.get("hallucination_rate", review.get("hallucination_score", 0.0))
        with self.session_factory() as db:
            db.add(
                ResourceReviewORM(
                    review_id=review_id,
                    resource_id=resource_id,
                    run_id=run_id,
                    status=status,
                    claim_total=claim_total,
                    claim_supported=claim_supported,
                    claim_unsupported=claim_unsupported,
                    suspected_hallucinations=review.get("suspected_hallucinations", claim_unsupported),
                    hallucination_rate=hallucination_rate,
                    review_pass_rate=review.get("review_pass_rate", 1.0 if status == "passed" else 0.0),
                    revision_count=review.get("revision_count", 0),
                    issues=review.get("issues", []),
                )
            )
            for claim in claims:
                db.add(
                    ResourceClaimORM(
                        claim_id=str(claim.get("claim_id") or uuid.uuid4()),
                        review_id=review_id,
                        resource_id=resource_id,
                        knowledge_point=claim.get("knowledge_point"),
                        claim_text=claim.get("text") or claim.get("claim_text", ""),
                        supported=bool(claim.get("supported", False)),
                        confidence=claim.get("confidence"),
                        evidence_refs=[
                            _as_dict(ref) for ref in claim.get("evidence_refs", [])
                        ],
                        issue_type=claim.get("issue_type"),
                        correction=claim.get("correction"),
                        review_comment=claim.get("review_comment"),
                    )
                )
            db.commit()
        return review_id

    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        with self.session_factory() as db:
            review = (
                db.query(ResourceReviewORM)
                .filter_by(resource_id=resource_id)
                .order_by(ResourceReviewORM.created_at.desc())
                .first()
            )
            if review is None:
                return None
            claims = (
                db.query(ResourceClaimORM)
                .filter_by(review_id=review.review_id)
                .order_by(ResourceClaimORM.claim_id)
                .all()
            )
            return ReviewSummary(
                review_id=review.review_id,
                resource_id=review.resource_id,
                status=review.status,
                claim_total=review.claim_total,
                claim_supported=review.claim_supported,
                claim_unsupported=review.claim_unsupported,
                suspected_hallucinations=review.suspected_hallucinations,
                hallucination_rate=review.hallucination_rate,
                review_pass_rate=review.review_pass_rate,
                revision_count=review.revision_count,
                issues=review.issues or [],
                claims=[
                    ResourceClaim(
                        claim_id=claim.claim_id,
                        text=claim.claim_text,
                        knowledge_point=claim.knowledge_point,
                        supported=claim.supported,
                        confidence=claim.confidence,
                        evidence_refs=[
                            SourceRef(
                                doc_id=ref.get("doc_id", "unknown"),
                                title=ref.get("title", ref.get("doc_id", "未知来源")),
                                snippet=ref.get("snippet", ""),
                                score=float(ref.get("score", 0.0)),
                                chunk_id=ref.get("chunk_id"),
                                source_path=ref.get("source_path"),
                                metadata=ref,
                            )
                            for ref in (claim.evidence_refs or [])
                        ],
                        issue_type=claim.issue_type,
                        correction=claim.correction,
                        review_comment=claim.review_comment,
                    )
                    for claim in claims
                ],
            )
