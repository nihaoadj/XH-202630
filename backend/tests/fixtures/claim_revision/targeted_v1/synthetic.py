"""Synthetic builders for Claim targeted-revision tests.

Every value here is synthetic.  These helpers never touch real user text,
secrets, or the E1 evaluation database; they only construct the frozen domain
objects the T46 constructors consume.
"""

from __future__ import annotations

import hashlib

from app.core.retrieval.knowledge_ids import sha256_hex
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claims import (
    ClaimJudgeType,
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)


def _claim_id(seed: str) -> str:
    return "clm_" + hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]


def _judgement_id(claim_id: str) -> str:
    return "jdg_" + hashlib.sha256(claim_id.encode("utf-8")).hexdigest()[:32]


def make_claim(
    *,
    seed: str,
    resource_id: str,
    resource_version: int = 1,
    run_id: str = "run",
    review_id: str = "review",
    claim_index: int = 0,
    claim_text: str = "合成断言",
    source_text: str = "合成原文",
    source_start: int = 0,
    source_end: int = 4,
    knowledge_point_id: str | None = None,
    source_evidence_ids: list[str] | None = None,
) -> ClaimRecord:
    return ClaimRecord(
        claim_id=_claim_id(seed),
        run_id=run_id,
        resource_id=resource_id,
        resource_version=resource_version,
        review_id=review_id,
        claim_index=claim_index,
        claim_text=claim_text,
        claim_type=ClaimType.FACTUAL,
        source_text=source_text,
        source_start=source_start,
        source_end=source_end,
        source_text_hash=sha256_hex(source_text),
        knowledge_point_id=knowledge_point_id,
        source_evidence_ids=source_evidence_ids or [],
        extractor_prompt_version="synthetic-v1",
        claim_hash=sha256_hex(f"{seed}:{claim_text}"),
    )


def make_judgement(
    *,
    claim: ClaimRecord,
    verdict: ClaimVerdict = ClaimVerdict.CONTRADICTED,
    evidence_ids: list[str] | None = None,
    reason: str = "合成判定理由",
    resource_version: int | None = None,
) -> ClaimJudgement:
    if evidence_ids is None:
        evidence_ids = ["evidence"] if verdict == ClaimVerdict.CONTRADICTED else []
    return ClaimJudgement(
        judgement_id=_judgement_id(claim.claim_id),
        claim_id=claim.claim_id,
        run_id=claim.run_id,
        resource_id=claim.resource_id,
        resource_version=resource_version or claim.resource_version,
        review_id=claim.review_id,
        status=ClaimJudgementStatus.COMPLETED,
        verdict=verdict,
        evidence_ids=evidence_ids,
        reason=reason,
        judge_type=ClaimJudgeType.DETERMINISTIC,
        judge_prompt_version="synthetic-v1",
        confidence=0.99,
    )


def make_resource(
    *,
    resource_id: str = "parent",
    resource_spec_id: str = "spec",
    resource_type: str = "讲义",
    content_text: str = "# 合成正文\n\n第一段。",
    version: int = 1,
    knowledge_points: list[str] | None = None,
    structured: dict | None = None,
) -> LearningResource:
    resource = LearningResource(
        resource_id=resource_id,
        learner_id="learner",
        run_id="run",
        batch_id="batch",
        resource_spec_id=resource_spec_id,
        resource_family_id="family",
        resource_type=resource_type,
        difficulty="初级",
        content_text=content_text,
        knowledge_points=knowledge_points or ["node"],
        source_refs=[],
        version=version,
    )
    if structured is not None:
        resource = resource.model_copy(update=structured)
    return resource
