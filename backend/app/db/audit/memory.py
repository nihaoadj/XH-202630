import uuid
from typing import Any, Iterable, Optional

from app.db.audit.base import BaseAuditRepository
from app.models.schemas import ResourceClaim, ReviewSummary, SourceRef


class MemoryAuditRepository(BaseAuditRepository):
    """用于单元测试与 DB_TYPE=memory 的轻量实现。"""

    def __init__(self):
        self.runs: dict[str, dict[str, Any]] = {}
        self.reviews: dict[str, dict[str, Any]] = {}

    def save_run(self, learner_id, knowledge_base_id, topic, trace: Iterable[dict[str, Any]], input_payload, output_payload, status, run_id=None):
        run_id = run_id or str(uuid.uuid4())
        self.runs[run_id] = {
            "learner_id": learner_id,
            "knowledge_base_id": knowledge_base_id,
            "topic": topic,
            "trace": list(trace),
            "input_payload": input_payload,
            "output_payload": output_payload,
            "status": status,
        }
        return run_id

    def save_review(self, resource_id: str, review: dict[str, Any], run_id: Optional[str]) -> str:
        review_id = review.get("review_ids", {}).get(resource_id) or review.get("review_id") or str(uuid.uuid4())
        self.reviews[review_id] = {"resource_id": resource_id, "run_id": run_id, **review}
        return review_id

    def get_review_by_resource(self, resource_id: str) -> Optional[ReviewSummary]:
        for review_id, review in reversed(list(self.reviews.items())):
            if review["resource_id"] != resource_id:
                continue
            claims = [
                ResourceClaim(
                    claim_id=str(claim.get("claim_id", "")),
                    text=claim.get("text") or claim.get("claim_text", ""),
                    knowledge_point=claim.get("knowledge_point"),
                    supported=bool(claim.get("supported", False)),
                    confidence=claim.get("confidence"),
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
                        for ref in claim.get("evidence_refs", [])
                    ],
                    issue_type=claim.get("issue_type"),
                    correction=claim.get("correction"),
                    review_comment=claim.get("review_comment"),
                )
                for claim in review.get("claims", [])
            ]
            status = review.get("status") or ("passed" if review.get("passed") else "needs_review")
            return ReviewSummary(
                review_id=review_id,
                resource_id=resource_id,
                status=status,
                claim_total=review.get("claim_total", len(claims)),
                claim_supported=review.get("claim_supported", sum(claim.supported for claim in claims)),
                claim_unsupported=review.get("claim_unsupported", sum(not claim.supported for claim in claims)),
                suspected_hallucinations=review.get("suspected_hallucinations", sum(not claim.supported for claim in claims)),
                hallucination_rate=review.get("hallucination_rate", review.get("hallucination_score", 0.0)),
                review_pass_rate=review.get(
                    "review_pass_rate",
                    1.0 if review.get("passed") or status in {"approve", "approved", "passed"} else 0.0,
                ),
                revision_count=review.get("revision_count", 0),
                issues=review.get("issues", []),
                claims=claims,
            )
        return None
