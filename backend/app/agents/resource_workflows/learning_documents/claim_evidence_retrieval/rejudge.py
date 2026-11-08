"""Round-1 rejudgement: batching, validation and hard-block classification."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.models.knowledge.knowledge import EvidenceItem
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSessionV1,
    ClaimSupplementJudgementLLMOutput,
    ClaimSupplementJudgementV1,
    batch_id_for,
    supplement_judgement_id,
)
from app.models.reviews.claims import (
    ClaimJudgementStatus,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.shared.persistence import canonical_hash


HARD_BLOCK_CONTRADICTED = "contradicted"
HARD_BLOCK_EVIDENCE_CONFLICT = "evidence_conflict"


@dataclass(frozen=True)
class RejudgeBatch:
    batch_id: str
    ordinal: int
    claim_ids: tuple[str, ...]
    input_hash: str
    payload: dict
    estimated_input_tokens: int

    @property
    def messages_payload(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def _estimated(payload: dict, policy: ClaimEvidenceRetrievalPolicyV1) -> int:
    from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.queries import (
        estimate_tokens,
    )

    return estimate_tokens(json.dumps(payload, ensure_ascii=False))


def build_rejudge_batches(
    claims: Sequence[ClaimRecord],
    *,
    evidence: Sequence[EvidenceItem],
    session_id: str,
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> tuple[tuple[RejudgeBatch, ...], tuple[str, ...]]:
    """Token-aware batches; an oversize evidence pool is reported, not cut."""

    allowed = [
        {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
        for item in evidence
    ]
    batches: list[RejudgeBatch] = []
    oversize: list[str] = []
    ordinal = 0

    def payload_for(group: Sequence[ClaimRecord]) -> dict:
        return {
            "round": 1,
            "allowed_evidence": allowed,
            "claims": [
                {
                    "claim_id": item.claim_id,
                    "claim_type": item.claim_type.value,
                    "claim_text": item.claim_text,
                    "resource_id": item.resource_id,
                    "resource_version": item.resource_version,
                }
                for item in group
            ],
        }

    def emit(group: Sequence[ClaimRecord]) -> None:
        nonlocal ordinal
        if not group:
            return
        payload = payload_for(group)
        estimated = _estimated(payload, policy)
        if estimated + policy.rejudge_output_cap > (
            policy.rejudge_input_cap + policy.rejudge_output_cap
        ):
            if len(group) == 1:
                oversize.append(group[0].claim_id)
                return
            middle = len(group) // 2
            emit(group[:middle])
            emit(group[middle:])
            return
        input_hash = canonical_hash(payload)
        batch_id = batch_id_for(
            session_id=session_id, kind="rejudge", ordinal=ordinal, input_hash=input_hash,
        )
        batches.append(RejudgeBatch(
            batch_id=batch_id,
            ordinal=ordinal,
            claim_ids=tuple(item.claim_id for item in group),
            input_hash=input_hash,
            payload={**payload, "batch_id": batch_id, "input_hash": input_hash},
            estimated_input_tokens=estimated,
        ))
        ordinal += 1

    ordered = list(claims)
    for start in range(0, len(ordered), policy.rejudge_batch_claims):
        emit(ordered[start:start + policy.rejudge_batch_claims])
    return tuple(batches), tuple(oversize)


def target_claims(
    claims: Sequence[ClaimRecord],
    *,
    effective_verdicts: dict[str, ClaimVerdict],
) -> list[ClaimRecord]:
    """Only first-round ``not_in_evidence`` factual Claims are rejudged."""

    return [
        item for item in claims
        if item.claim_type is ClaimType.FACTUAL
        and effective_verdicts.get(item.claim_id) is ClaimVerdict.NOT_IN_EVIDENCE
    ]


def validate_rejudge_output(
    output: ClaimSupplementJudgementLLMOutput,
    *,
    batch: RejudgeBatch,
    claims: dict[str, ClaimRecord],
    allowed_evidence_ids: set[str],
) -> tuple[list[dict], str | None]:
    """Validate shape and return ``(candidates, hard_block_reason)``."""

    returned = [item.claim_id for item in output.judgements]
    if len(returned) != len(set(returned)):
        raise ValueError("rejudge repeats a claim")
    if set(returned) != set(batch.claim_ids):
        raise ValueError("rejudge claim set mismatch")
    hard_block: str | None = None
    candidates: list[dict] = []
    for item in output.judgements:
        claim = claims[item.claim_id]
        if claim.claim_type is not ClaimType.FACTUAL:
            raise ValueError("non-factual claim entered round-1 rejudgement")
        if item.verdict is ClaimVerdict.NON_FACTUAL:
            raise ValueError("factual claim cannot receive a non_factual verdict")
        unknown = set(item.evidence_ids) - allowed_evidence_ids
        if unknown:
            raise ValueError("rejudge references evidence outside the authorised scope")
        if item.verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} and not item.evidence_ids:
            raise ValueError("supported/contradicted requires evidence")
        if item.verdict is ClaimVerdict.NOT_IN_EVIDENCE and item.evidence_ids:
            raise ValueError("not_in_evidence forbids evidence")
        if item.evidence_conflict:
            unknown_conflict = set(item.conflicting_evidence_ids) - allowed_evidence_ids
            if unknown_conflict:
                raise ValueError("conflict references evidence outside the scope")
            hard_block = HARD_BLOCK_EVIDENCE_CONFLICT
        if item.verdict is ClaimVerdict.CONTRADICTED:
            hard_block = hard_block or HARD_BLOCK_CONTRADICTED
        candidates.append(item.model_dump(mode="json"))
    return candidates, hard_block


def materialize_supplements(
    *,
    session: ClaimEvidenceRetrievalSessionV1,
    batch: RejudgeBatch,
    candidates: Sequence[dict],
    claims: dict[str, ClaimRecord],
    allowed_evidence_ids: set[str],
    scope_id: str,
    scope_hash: str,
    prompt_version: str,
    prompt_hash: str,
    model_name: str | None,
    created_at: datetime | None = None,
) -> list[ClaimSupplementJudgementV1]:
    stamp = created_at or datetime.now(timezone.utc)
    result: list[ClaimSupplementJudgementV1] = []
    for candidate in candidates:
        claim = claims[candidate["claim_id"]]
        payload = {
            "claim_id": claim.claim_id,
            "session_id": session.session_id,
            "scope_id": scope_id,
            "verdict": candidate["verdict"],
            "evidence_ids": sorted(candidate["evidence_ids"]),
            "evidence_conflict": candidate["evidence_conflict"],
            "conflicting_evidence_ids": sorted(candidate["conflicting_evidence_ids"]),
            "reason": candidate["reason"],
        }
        result.append(ClaimSupplementJudgementV1(
            judgement_id=supplement_judgement_id(
                claim_id=claim.claim_id,
                session_id=session.session_id,
                scope_hash=scope_hash,
                prompt_hash=prompt_hash,
            ),
            session_id=session.session_id,
            claim_id=claim.claim_id,
            run_id=claim.run_id,
            resource_id=claim.resource_id,
            resource_version=claim.resource_version,
            review_id=claim.review_id,
            round_no=1,
            scope_id=scope_id,
            status=ClaimJudgementStatus.COMPLETED,
            verdict=ClaimVerdict(candidate["verdict"]),
            evidence_ids=list(candidate["evidence_ids"]),
            conflicting_evidence_ids=list(candidate["conflicting_evidence_ids"]),
            evidence_conflict=bool(candidate["evidence_conflict"]),
            reason=str(candidate["reason"]),
            judge_model=model_name,
            judge_prompt_version=prompt_version,
            confidence=float(candidate["confidence"]),
            payload_hash=canonical_hash(payload),
            created_at=stamp,
        ))
    return result


__all__ = [
    "HARD_BLOCK_CONTRADICTED",
    "HARD_BLOCK_EVIDENCE_CONFLICT",
    "RejudgeBatch",
    "build_rejudge_batches",
    "materialize_supplements",
    "target_claims",
    "validate_rejudge_output",
]
