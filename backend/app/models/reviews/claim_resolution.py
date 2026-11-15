"""Pure resolution of the single effective Claim judgement set.

Every production reader (workflow state, quality projection, report snapshot,
publication gate) must resolve through this module.  It never reads the
database and never guesses from timestamps: a supplement replaces the first
round only when its session is explicitly activated in a completed round.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimMetricSummary,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
    compute_claim_metric,
)


class ClaimResolutionConflict(ValueError):
    """The stored judgement set cannot be projected without guessing."""


@dataclass(frozen=True)
class ClaimResolution:
    judgements: Mapping[str, ClaimJudgement]
    activated_session_ids: tuple[str, ...] = ()
    blocked_session_ids: tuple[str, ...] = ()
    substituted_claim_ids: tuple[str, ...] = ()
    supplemental_evidence_ids: tuple[str, ...] = ()

    def ordered(self) -> list[ClaimJudgement]:
        return sorted(
            self.judgements.values(),
            key=lambda item: (item.resource_id, item.resource_version, item.claim_id),
        )

    def verdict_for(self, claim_id: str) -> ClaimVerdict | None:
        item = self.judgements.get(claim_id)
        return item.verdict if item is not None else None


@dataclass(frozen=True)
class RevisionProblem:
    claim_id: str
    resource_id: str
    resource_version: int
    code: str
    reason: str
    origin: str
    evidence_ids: tuple[str, ...] = ()
    hard_block: bool = False


def _completed(items: Iterable[ClaimJudgement]) -> list[ClaimJudgement]:
    return [
        item for item in items
        if item.status is ClaimJudgementStatus.COMPLETED and item.verdict is not None
    ]


def _single_initial_judgements(
    initial: Sequence[ClaimJudgement],
    *,
    exempt_claim_ids: set[str],
) -> dict[str, ClaimJudgement]:
    result: dict[str, ClaimJudgement] = {}
    for item in _completed(initial):
        previous = result.get(item.claim_id)
        if previous is None:
            result[item.claim_id] = item
            continue
        if previous.verdict == item.verdict:
            # Historical duplicates with the same verdict are not a conflict,
            # but the projected row must still be deterministic.
            if (item.created_at, item.judgement_id) > (previous.created_at, previous.judgement_id):
                result[item.claim_id] = item
            continue
        if item.claim_id in exempt_claim_ids:
            # A round-1 supplement replaces this claim entirely.  Only the
            # absence verdict is a valid first-round input for that supplement;
            # picking a positive verdict here would silently widen the feature.
            if item.verdict is ClaimVerdict.NOT_IN_EVIDENCE:
                result[item.claim_id] = item
            elif previous.verdict is not ClaimVerdict.NOT_IN_EVIDENCE:
                raise ClaimResolutionConflict(
                    f"claim {item.claim_id} was never not_in_evidence"
                )
            continue
        raise ClaimResolutionConflict(
            f"claim {item.claim_id} has conflicting completed verdicts"
        )
    return result


def _validate_activated_session(
    session: ClaimEvidenceRetrievalSessionV1,
    supplements: Sequence[ClaimSupplementJudgementV1],
) -> dict[str, ClaimSupplementJudgementV1]:
    if session.status is not ClaimEvidenceRetrievalStatus.COMPLETED:
        raise ClaimResolutionConflict(
            f"activated session {session.session_id} is not completed"
        )
    by_claim: dict[str, ClaimSupplementJudgementV1] = {}
    for item in supplements:
        if item.session_id != session.session_id:
            continue
        if item.claim_id not in set(session.target_claim_ids):
            raise ClaimResolutionConflict(
                f"session {session.session_id} judged a non-target claim"
            )
        previous = by_claim.get(item.claim_id)
        if previous is not None and previous.judgement_id != item.judgement_id:
            raise ClaimResolutionConflict(
                f"session {session.session_id} judged claim {item.claim_id} twice"
            )
        by_claim[item.claim_id] = item
    if set(by_claim) != set(session.target_claim_ids):
        raise ClaimResolutionConflict(
            f"session {session.session_id} activation is incomplete"
        )
    for item in by_claim.values():
        if item.status is not ClaimJudgementStatus.COMPLETED:
            raise ClaimResolutionConflict(
                f"session {session.session_id} contains an incomplete supplement"
            )
    return by_claim


def resolve_effective_claim_judgements(
    initial: Sequence[ClaimJudgement],
    sessions: Sequence[ClaimEvidenceRetrievalSessionV1] = (),
    supplements: Sequence[ClaimSupplementJudgementV1] = (),
) -> ClaimResolution:
    """Return one effective judgement per claim, round-0 first, round-1 last."""

    activated = [
        item for item in sessions
        if item.active and item.status is ClaimEvidenceRetrievalStatus.COMPLETED
    ]
    activated.sort(key=lambda item: (item.resource_version, item.created_at, item.session_id))
    bindings = {
        (item.run_id, item.resource_id, item.resource_version, item.review_id)
        for item in activated
    }
    if len(bindings) != len(activated):
        raise ClaimResolutionConflict("multiple activated sessions share one version")

    replacements: dict[str, ClaimJudgement] = {}
    substituted: list[str] = []
    supplemental_evidence: list[str] = []
    for session in activated:
        by_claim = _validate_activated_session(session, supplements)
        for claim_id, supplement in by_claim.items():
            judgement = supplement.as_judgement()
            replacements[claim_id] = judgement
            substituted.append(claim_id)
            supplemental_evidence.extend(judgement.evidence_ids)
            supplemental_evidence.extend(supplement.conflicting_evidence_ids)

    effective_initial = _single_initial_judgements(
        initial, exempt_claim_ids=set(replacements),
    )
    for claim_id in replacements:
        original = effective_initial.get(claim_id)
        if original is None:
            raise ClaimResolutionConflict(
                f"supplement for claim {claim_id} has no first-round judgement"
            )
        if original.verdict is not ClaimVerdict.NOT_IN_EVIDENCE:
            raise ClaimResolutionConflict(
                f"claim {claim_id} was not not_in_evidence in round 0"
            )

    merged: dict[str, ClaimJudgement] = dict(effective_initial)
    merged.update(replacements)
    blocked = sorted({
        item.session_id for item in sessions
        if item.hard_block and not item.active
    })
    return ClaimResolution(
        judgements=merged,
        activated_session_ids=tuple(item.session_id for item in activated),
        blocked_session_ids=tuple(blocked),
        substituted_claim_ids=tuple(sorted(substituted)),
        supplemental_evidence_ids=tuple(dict.fromkeys(supplemental_evidence)),
    )


def resolve_claim_metric(
    claims: Sequence[ClaimRecord],
    resolution: ClaimResolution,
) -> ClaimMetricSummary:
    """Metrics always use every factual Claim as the denominator."""

    return compute_claim_metric(claims, resolution.judgements.values())


def resolve_claim_revision_problems(
    *,
    claims: Sequence[ClaimRecord],
    resolution: ClaimResolution,
    validated_inactive_contradictions: Mapping[str, ClaimSupplementJudgementV1] | None = None,
) -> list[RevisionProblem]:
    """Build the targeted-revision work list without trusting unactivated work.

    ``validated_inactive_contradictions`` may only contain supplements that were
    already persisted together with a hard block.  Failed batches never appear
    here, because an absent judgement is not a factual verdict.
    """

    claim_index = {item.claim_id: item for item in claims}
    problems: list[RevisionProblem] = []
    seen: set[str] = set()
    inactive = dict(validated_inactive_contradictions or {})
    for claim_id, judgement in resolution.judgements.items():
        claim = claim_index.get(claim_id)
        if claim is None or claim.claim_type is not ClaimType.FACTUAL:
            continue
        if judgement.verdict not in {ClaimVerdict.CONTRADICTED, ClaimVerdict.NOT_IN_EVIDENCE}:
            continue
        persisted = inactive.get(claim_id)
        if persisted is not None:
            # A persisted round-1 contradiction outranks a round-0 absence: the
            # new risk is the stronger, already-audited statement.
            problems.append(RevisionProblem(
                claim_id=claim.claim_id,
                resource_id=claim.resource_id,
                resource_version=claim.resource_version,
                code="factual_risk",
                reason=persisted.reason,
                origin="supplement_inactive",
                evidence_ids=tuple(persisted.evidence_ids),
                hard_block=True,
            ))
            seen.add(claim_id)
            continue
        problems.append(RevisionProblem(
            claim_id=claim.claim_id,
            resource_id=claim.resource_id,
            resource_version=claim.resource_version,
            code=("factual_risk" if judgement.verdict is ClaimVerdict.CONTRADICTED
                  else "evidence_gap"),
            reason=judgement.reason,
            origin="effective",
            evidence_ids=tuple(judgement.evidence_ids),
            hard_block=judgement.verdict is ClaimVerdict.CONTRADICTED,
        ))
        seen.add(claim_id)
    for claim_id, supplement in inactive.items():
        if claim_id in seen:
            continue
        claim = claim_index.get(claim_id)
        if claim is None or claim.claim_type is not ClaimType.FACTUAL:
            continue
        problems.append(RevisionProblem(
            claim_id=claim.claim_id,
            resource_id=claim.resource_id,
            resource_version=claim.resource_version,
            code="factual_risk",
            reason=supplement.reason,
            origin="supplement_inactive",
            evidence_ids=tuple(supplement.evidence_ids),
            hard_block=True,
        ))
    return sorted(
        problems,
        key=lambda item: (item.resource_id, item.resource_version, item.claim_id),
    )


__all__ = [
    "ClaimResolution",
    "ClaimResolutionConflict",
    "RevisionProblem",
    "resolve_claim_metric",
    "resolve_claim_revision_problems",
    "resolve_effective_claim_judgements",
]
