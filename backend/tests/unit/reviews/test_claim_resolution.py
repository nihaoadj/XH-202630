"""Effective Claim judgement resolution: round 0 first, round 1 only when active."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalSessionV1,
    ClaimEvidenceRetrievalStatus,
    ClaimSupplementJudgementV1,
)
from app.models.reviews.claim_resolution import (
    ClaimResolutionConflict,
    resolve_claim_metric,
    resolve_claim_revision_problems,
    resolve_effective_claim_judgements,
)
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimJudgeType,
    ClaimMetricStatus,
    ClaimRecord,
    ClaimType,
    ClaimVerdict,
)

NOW = datetime(2026, 11, 8, 8, 0, 0, tzinfo=timezone.utc)


def claim(index: int, *, verdict_word: str = "one") -> ClaimRecord:
    return ClaimRecord(
        claim_id="clm_" + f"{index:032x}",
        run_id="run-1",
        resource_id="res-1",
        resource_version=1,
        review_id="rev-1",
        claim_index=index,
        claim_text=f"claim text {index} {verdict_word}",
        claim_type=ClaimType.FACTUAL,
        source_text="source",
        source_start=0,
        source_end=6,
        source_text_hash="a" * 64,
        extractor_prompt_version="p",
        claim_hash="b" * 64,
        created_at=NOW,
    )


def judgement(record: ClaimRecord, verdict: ClaimVerdict, *, session: bool = False) -> ClaimJudgement:
    evidence = ["ev-base"] if verdict in {ClaimVerdict.SUPPORTED, ClaimVerdict.CONTRADICTED} else []
    return ClaimJudgement(
        judgement_id="jdg_" + ("c" if session else "d") + record.claim_id[5:],
        claim_id=record.claim_id,
        run_id=record.run_id,
        resource_id=record.resource_id,
        resource_version=record.resource_version,
        review_id=record.review_id,
        status=ClaimJudgementStatus.COMPLETED,
        verdict=verdict,
        evidence_ids=evidence,
        reason="reason",
        judge_type=ClaimJudgeType.LLM,
        judge_prompt_version="p0-06-judge-v1",
        confidence=0.8,
        created_at=NOW,
    )


def session(
    *, status: ClaimEvidenceRetrievalStatus, active: bool,
    hard_block: bool = False, targets: list[str] | None = None,
) -> ClaimEvidenceRetrievalSessionV1:
    return ClaimEvidenceRetrievalSessionV1(
        session_id="cers_" + "1" * 32,
        run_id="run-1", resource_id="res-1", resource_version=1, review_id="rev-1",
        content_hash="a" * 64, policy_hash="b" * 64,
        base_evidence_set_hash="c" * 64, initial_judgement_hash="d" * 64,
        target_claim_ids=targets or [],
        status=status,
        active=active,
        hard_block=hard_block,
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW if status in {
            ClaimEvidenceRetrievalStatus.COMPLETED,
            ClaimEvidenceRetrievalStatus.BLOCKED,
            ClaimEvidenceRetrievalStatus.NO_NEW_EVIDENCE,
            ClaimEvidenceRetrievalStatus.UNAVAILABLE,
        } else None,
    )


def supplement(record: ClaimRecord, verdict: ClaimVerdict, *, session_id: str) -> ClaimSupplementJudgementV1:
    return ClaimSupplementJudgementV1(
        judgement_id="jdg_" + "e" * 32,
        session_id=session_id,
        claim_id=record.claim_id,
        run_id=record.run_id,
        resource_id=record.resource_id,
        resource_version=record.resource_version,
        review_id=record.review_id,
        scope_id="cevs_" + "2" * 32,
        status=ClaimJudgementStatus.COMPLETED,
        verdict=verdict,
        evidence_ids=["ev-new"] if verdict is ClaimVerdict.SUPPORTED else [],
        reason="round-1",
        judge_prompt_version="claim-evidence-rejudge-v1",
        confidence=0.7,
        payload_hash="f" * 64,
        created_at=NOW,
    )


def test_without_sessions_round_zero_is_effective():
    records = [claim(1), claim(2)]
    round0 = [judgement(records[0], ClaimVerdict.SUPPORTED), judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE)]

    resolution = resolve_effective_claim_judgements(round0)

    assert {key: value.verdict for key, value in resolution.judgements.items()} == {
        records[0].claim_id: ClaimVerdict.SUPPORTED,
        records[1].claim_id: ClaimVerdict.NOT_IN_EVIDENCE,
    }
    assert resolution.activated_session_ids == ()


def test_activated_session_replaces_only_the_not_in_evidence_claim():
    records = [claim(1), claim(2), claim(3)]
    round0 = [
        judgement(records[0], ClaimVerdict.SUPPORTED),
        judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE),
        judgement(records[2], ClaimVerdict.CONTRADICTED),
    ]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[1].claim_id],
    )
    resolution = resolve_effective_claim_judgements(
        round0, [active], [supplement(records[1], ClaimVerdict.SUPPORTED, session_id=active.session_id)],
    )

    assert resolution.judgements[records[0].claim_id].verdict is ClaimVerdict.SUPPORTED
    assert resolution.judgements[records[1].claim_id].verdict is ClaimVerdict.SUPPORTED
    assert resolution.judgements[records[2].claim_id].verdict is ClaimVerdict.CONTRADICTED
    assert resolution.activated_session_ids == (active.session_id,)
    assert resolution.substituted_claim_ids == (records[1].claim_id,)


def test_supplement_for_a_non_target_claim_is_rejected():
    records = [claim(1), claim(2)]
    round0 = [judgement(records[0], ClaimVerdict.SUPPORTED), judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE)]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[1].claim_id],
    )
    with pytest.raises(ClaimResolutionConflict):
        resolve_effective_claim_judgements(
            round0, [active],
            [supplement(records[0], ClaimVerdict.CONTRADICTED, session_id=active.session_id)],
        )


def test_incomplete_activation_is_rejected():
    records = [claim(1), claim(2)]
    round0 = [judgement(records[0], ClaimVerdict.NOT_IN_EVIDENCE), judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE)]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[0].claim_id, records[1].claim_id],
    )
    with pytest.raises(ClaimResolutionConflict):
        resolve_effective_claim_judgements(
            round0, [active],
            [supplement(records[0], ClaimVerdict.SUPPORTED, session_id=active.session_id)],
        )


def test_blocked_and_inactive_sessions_never_substitute():
    records = [claim(1)]
    round0 = [judgement(records[0], ClaimVerdict.NOT_IN_EVIDENCE)]
    blocked = session(
        status=ClaimEvidenceRetrievalStatus.BLOCKED, active=False,
        hard_block=True, targets=[records[0].claim_id],
    )
    resolution = resolve_effective_claim_judgements(
        round0, [blocked], [supplement(records[0], ClaimVerdict.SUPPORTED, session_id=blocked.session_id)],
    )

    assert resolution.judgements[records[0].claim_id].verdict is ClaimVerdict.NOT_IN_EVIDENCE
    assert resolution.blocked_session_ids == (blocked.session_id,)


def test_supplement_for_a_claim_that_was_supported_is_rejected():
    records = [claim(1)]
    round0 = [judgement(records[0], ClaimVerdict.SUPPORTED)]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[0].claim_id],
    )
    with pytest.raises(ClaimResolutionConflict):
        resolve_effective_claim_judgements(
            round0, [active],
            [supplement(records[0], ClaimVerdict.NOT_IN_EVIDENCE, session_id=active.session_id)],
        )


def test_metric_uses_every_factual_claim_as_denominator():
    records = [claim(1), claim(2), claim(3)]
    round0 = [
        judgement(records[0], ClaimVerdict.SUPPORTED),
        judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE),
        judgement(records[2], ClaimVerdict.NOT_IN_EVIDENCE),
    ]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[1].claim_id, records[2].claim_id],
    )
    resolution = resolve_effective_claim_judgements(
        round0, [active],
        [
            supplement(records[1], ClaimVerdict.SUPPORTED, session_id=active.session_id),
            supplement(records[2], ClaimVerdict.NOT_IN_EVIDENCE, session_id=active.session_id),
        ],
    )

    summary = resolve_claim_metric(records, resolution)

    assert summary.metric_status is ClaimMetricStatus.COMPLETE
    assert summary.factual_claim_total == 3
    assert summary.supported_claim_total == 2
    assert summary.not_in_evidence_claim_total == 1
    assert summary.claim_hallucination_rate == pytest.approx(1 / 3)


def test_two_activated_sessions_for_one_version_are_rejected():
    records = [claim(1)]
    round0 = [judgement(records[0], ClaimVerdict.NOT_IN_EVIDENCE)]
    first = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[0].claim_id],
    )
    second = first.model_copy(update={"session_id": "cers_" + "9" * 32})
    with pytest.raises(ClaimResolutionConflict):
        resolve_effective_claim_judgements(round0, [first, second], [])


def test_revision_problems_prioritise_effective_and_add_inactive_contradictions():
    records = [claim(1), claim(2)]
    round0 = [
        judgement(records[0], ClaimVerdict.NOT_IN_EVIDENCE),
        judgement(records[1], ClaimVerdict.NOT_IN_EVIDENCE),
    ]
    active = session(
        status=ClaimEvidenceRetrievalStatus.COMPLETED, active=True,
        targets=[records[0].claim_id],
    )
    resolution = resolve_effective_claim_judgements(
        round0, [active],
        [supplement(records[0], ClaimVerdict.NOT_IN_EVIDENCE, session_id=active.session_id)],
    )
    inactive = supplement(records[1], ClaimVerdict.CONTRADICTED, session_id=active.session_id)

    problems = resolve_claim_revision_problems(
        claims=records, resolution=resolution,
        validated_inactive_contradictions={records[1].claim_id: inactive},
    )

    assert [item.claim_id for item in problems] == [records[0].claim_id, records[1].claim_id]
    assert problems[0].code == "evidence_gap"
    assert problems[1].code == "factual_risk"
    assert problems[1].origin == "supplement_inactive"
    assert problems[1].hard_block is True


def test_round_zero_disagreement_without_supplement_is_still_a_conflict():
    records = [claim(1)]
    first = judgement(records[0], ClaimVerdict.SUPPORTED)
    second = first.model_copy(update={"judgement_id": "jdg_" + "9" * 32, "verdict": ClaimVerdict.CONTRADICTED})
    with pytest.raises(ClaimResolutionConflict):
        resolve_effective_claim_judgements([first, second])
