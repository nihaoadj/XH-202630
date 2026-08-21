from __future__ import annotations

import pytest

from app.models.claims import (
    ClaimCandidate,
    ClaimJudgementCandidate,
    ClaimMetricStatus,
    ClaimType,
    ClaimVerdict,
    compute_claim_metric,
    materialize_claims,
    materialize_judgements,
    stable_claim_id,
)


def _claims():
    content = "Python 使用缩进定义代码块。先运行测试，再提交代码。"
    factual_source = "Python 使用缩进定义代码块。"
    instructional_source = "先运行测试，再提交代码。"
    candidates = [
        ClaimCandidate(
            claim_text="Python 使用缩进定义代码块",
            claim_type=ClaimType.FACTUAL,
            source_text=factual_source,
            source_start=0,
            source_end=len(factual_source),
            knowledge_point_id="skill-python",
            source_evidence_ids=["ev-1"],
        ),
        ClaimCandidate(
            claim_text="先运行测试",
            claim_type=ClaimType.INSTRUCTIONAL,
            source_text=instructional_source,
            source_start=len(factual_source),
            source_end=len(content),
        ),
    ]
    return materialize_claims(
        candidates=candidates,
        resource_content=content,
        resource_id="res-1",
        resource_version=2,
        review_id="rev-1",
        run_id="run-1",
        allowed_evidence_ids={"ev-1"},
        allowed_knowledge_point_ids={"skill-python"},
        extractor_prompt_version="p0-06-extract-v1",
        extractor_model="fake",
    )


def test_claim_id_is_stable_and_version_scoped():
    first = stable_claim_id("res", 1, 0, "  A  B ", "v1")
    assert first == stable_claim_id("res", 1, 0, "a b", "v1")
    assert first != stable_claim_id("res", 2, 0, "a b", "v1")


def test_materialize_claims_rejects_forged_evidence():
    with pytest.raises(ValueError, match="unknown evidence"):
        materialize_claims(
            candidates=[
                ClaimCandidate(
                    claim_text="事实",
                    claim_type=ClaimType.FACTUAL,
                    source_text="事实",
                    source_start=0,
                    source_end=2,
                    source_evidence_ids=["forged"],
                )
            ],
            resource_content="事实",
            resource_id="res",
            resource_version=1,
            review_id="rev",
            run_id="run",
            allowed_evidence_ids={"ev-1"},
            allowed_knowledge_point_ids=set(),
            extractor_prompt_version="v1",
            extractor_model=None,
        )


def test_metric_counts_claim_once_with_multiple_evidence():
    claims = _claims()
    judgements = materialize_judgements(
        claims=claims,
        candidates=[
            ClaimJudgementCandidate(
                claim_id=claims[0].claim_id,
                verdict=ClaimVerdict.SUPPORTED,
                evidence_ids=["ev-1", "ev-2"],
                reason="两条证据共同支持",
                confidence=0.9,
            ),
            ClaimJudgementCandidate(
                claim_id=claims[1].claim_id,
                verdict=ClaimVerdict.NON_FACTUAL,
                evidence_ids=[],
                reason="教学指令不参与事实指标",
                confidence=1.0,
            ),
        ],
        allowed_evidence_ids={"ev-1", "ev-2"},
        judge_prompt_version="p0-06-judge-v1",
        judge_model="fake",
    )
    metric = compute_claim_metric(claims, judgements)
    assert metric.metric_status == ClaimMetricStatus.COMPLETE
    assert metric.factual_claim_total == 1
    assert metric.supported_claim_total == 1
    assert metric.claim_hallucination_rate == 0.0


def test_metric_is_null_when_factual_judgement_is_incomplete():
    metric = compute_claim_metric(_claims(), [])
    assert metric.metric_status == ClaimMetricStatus.INCOMPLETE
    assert metric.claim_hallucination_rate is None


def test_no_factual_claim_is_not_applicable_not_a_pass():
    claims = _claims()[1:]
    judgements = materialize_judgements(
        claims=claims,
        candidates=[
            ClaimJudgementCandidate(
                claim_id=claims[0].claim_id,
                verdict=ClaimVerdict.NON_FACTUAL,
                reason="非事实",
                confidence=1.0,
            )
        ],
        allowed_evidence_ids=set(),
        judge_prompt_version="v1",
        judge_model=None,
    )
    metric = compute_claim_metric(claims, judgements)
    assert metric.metric_status == ClaimMetricStatus.NOT_APPLICABLE
    assert metric.claim_hallucination_rate == 0.0
