"""Quality projection must read the effective round, not the historical rows."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.audit.quality_read import QualitySourceBundle
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimJudgeType,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)
from app.models.learning_documents.schemas import LearningResource
from app.services.reviews.quality_query import ResourceQualityQueryService
from app.models.shared.persistence import WorkflowCheckpoint, canonical_hash

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)
RESOURCE_ID = "res-quality"


def _claim(index: int) -> ClaimRecord:
    return ClaimRecord(
        claim_id="clm_" + f"{index:032x}",
        run_id="run-q", resource_id=RESOURCE_ID, resource_version=1,
        review_id="rev-q", claim_index=index, claim_text=f"claim {index}",
        claim_type=ClaimType.FACTUAL, source_text="source",
        source_start=0, source_end=6, source_text_hash="a" * 64,
        extractor_prompt_version="p", claim_hash="b" * 64, created_at=NOW,
    )


def _judgement(claim: ClaimRecord, verdict: ClaimVerdict) -> ClaimJudgement:
    return ClaimJudgement(
        judgement_id="jdg_" + claim.claim_id[4:],
        claim_id=claim.claim_id, run_id=claim.run_id, resource_id=claim.resource_id,
        resource_version=1, review_id=claim.review_id,
        status=ClaimJudgementStatus.COMPLETED, verdict=verdict,
        evidence_ids=["ev-1"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} else [],
        reason="round0", judge_type=ClaimJudgeType.LLM,
        judge_prompt_version="p0-06-judge-v1", confidence=0.8, created_at=NOW,
    )


def _session(
    active: bool, status: ClaimEvidenceRetrievalStatus, *, targets: list[str],
) -> ClaimEvidenceRetrievalSessionV1:
    return ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32,
        run_id="run-q", resource_id=RESOURCE_ID, resource_version=1, review_id="rev-q",
        content_hash="a" * 64, policy_hash="b" * 64,
        base_evidence_set_hash="c" * 64, initial_judgement_hash="d" * 64,
        target_claim_ids=list(targets),
        status=status, active=active, completed_at=NOW, updated_at=NOW,
    )


def _supplement(claim: ClaimRecord) -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + "9" * 32,
        session_id="cers_" + "1" * 32, claim_id=claim.claim_id,
        run_id=claim.run_id, resource_id=claim.resource_id, resource_version=1,
        review_id=claim.review_id, scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED, verdict=ClaimVerdict.SUPPORTED,
        evidence_ids=["ev-new"], reason="round1",
        judge_prompt_version="claim-evidence-rejudge-v1", confidence=0.7,
        payload_hash="e" * 64, created_at=NOW,
    )


def _resource() -> LearningResource:
    return LearningResource(
        resource_id=RESOURCE_ID, resource_type="讲义", difficulty="中级",
        content_text="正文", knowledge_points=[], source_refs=[],
        run_id="run-q", version=1, review_id="rev-q",
    )


def _bundle(claims, judgements, sessions=(), supplements=()) -> QualitySourceBundle:
    projection = {
        "include_claim_check": True,
        "claim_check_status": "completed",
        "claim_failed_resource_ids": [],
    }
    checkpoint = WorkflowCheckpoint(
        checkpoint_id="cp-1", run_id="run-q", event_sequence=1, step_id="step-1",
        step_sequence=1, node_name="claim_supervisor",
        state_projection=projection,
        state_hash=canonical_hash(projection), created_at=NOW,
    )
    return QualitySourceBundle(
        run_id="run-q", read_mode="native_memory", claims=tuple(claims),
        judgements=tuple(judgements), supplement_sessions=tuple(sessions),
        supplement_judgements=tuple(supplements), checkpoints=(checkpoint,),
    )


def _quality(bundle):
    service = ResourceQualityQueryService(
        audit_repository=None, resource_repository=None, claim_repository=None,
    )
    return service._claim_quality(
        bundle, _resource(), claim_requested=True,
        ordinary_approved=True, ordinary_status="approve",
    )


def test_activated_round_one_is_the_effective_quality_value():
    claims = [_claim(1), _claim(2)]
    judgements = [_judgement(claims[0], ClaimVerdict.SUPPORTED), _judgement(claims[1], ClaimVerdict.NOT_IN_EVIDENCE)]
    bundle = _bundle(
        claims, judgements,
        sessions=[_session(
            True, ClaimEvidenceRetrievalStatus.COMPLETED, targets=[claims[1].claim_id],
        )],
        supplements=[_supplement(claims[1])],
    )

    quality = _quality(bundle)

    assert quality.status == "complete"
    assert quality.counts.factual_claim_total == 2
    assert quality.counts.supported_claim_total == 2
    assert quality.counts.not_in_evidence_claim_total == 0
    assert quality.hallucination.value == 0.0


def test_inactive_session_keeps_round_zero_visible():
    claims = [_claim(1), _claim(2)]
    judgements = [_judgement(claims[0], ClaimVerdict.SUPPORTED), _judgement(claims[1], ClaimVerdict.NOT_IN_EVIDENCE)]
    bundle = _bundle(
        claims, judgements,
        sessions=[_session(
            False, ClaimEvidenceRetrievalStatus.BLOCKED, targets=[claims[1].claim_id],
        )],
        supplements=[_supplement(claims[1])],
    )

    quality = _quality(bundle)

    assert quality.status == "complete"
    assert quality.counts.supported_claim_total == 1
    assert quality.counts.not_in_evidence_claim_total == 1
    assert quality.hallucination.value == 0.5


def test_historical_round_zero_disagreement_for_a_substituted_claim_is_not_a_conflict():
    claims = [_claim(1)]
    first = _judgement(claims[0], ClaimVerdict.NOT_IN_EVIDENCE)
    historical = first.model_copy(update={
        "judgement_id": "jdg_" + "8" * 32, "verdict": ClaimVerdict.SUPPORTED,
        "evidence_ids": ["ev-1"],
    })
    bundle = _bundle(
        claims, [first, historical],
        sessions=[_session(
            True, ClaimEvidenceRetrievalStatus.COMPLETED, targets=[claims[0].claim_id],
        )],
        supplements=[_supplement(claims[0])],
    )

    quality = _quality(bundle)

    assert quality.status == "complete"
    assert quality.counts.supported_claim_total == 1


def test_conflict_between_untouched_claims_is_still_detected():
    claims = [_claim(1), _claim(2)]
    first = _judgement(claims[0], ClaimVerdict.NOT_IN_EVIDENCE)
    other = first.model_copy(update={
        "judgement_id": "jdg_" + "7" * 32, "verdict": ClaimVerdict.CONTRADICTED,
        "evidence_ids": ["ev-1"],
    })
    bundle = _bundle(
        claims, [first, other, _judgement(claims[1], ClaimVerdict.SUPPORTED)],
        sessions=[_session(
            True, ClaimEvidenceRetrievalStatus.COMPLETED, targets=[claims[1].claim_id],
        )],
        supplements=[_supplement(claims[1])],
    )

    quality = _quality(bundle)

    assert quality.status == "incomplete"
    assert "CLAIM_JUDGEMENT_CONFLICT" in quality.reason_codes
