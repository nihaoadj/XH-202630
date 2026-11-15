"""T48 contract and pure-calculation matrix (deterministic, no IO).

Covers the frozen metric definitions: one coverage source, two isolated
hallucination sources, evaluation-only difficulty accuracy, and the rule that
unknown/failed/not-applicable states never become a number.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.reviews.claims import ClaimMetricStatus, ClaimMetricSummary
from app.models.reviews.quality_metrics import (
    CLAIM_RISK_DEFINITION_VERSION,
    COVERAGE_DEFINITION_VERSION,
    DIFFICULTY_ACCURACY_DEFINITION_VERSION,
    ORDINARY_REFERENCE_DEFINITION_VERSION,
    ORDINARY_REFERENCE_VALUE,
    ClaimQualityV1,
    CoverageTargetV1,
    DifficultyFitV1,
    IssueStatisticsV1,
    QualityAssessment,
    QualityEvidenceMode,
    QualityMetricId,
    QualityMetricSource,
    QualityMetricStatus,
    RateMetricV1,
    ResourceQualityMetricsV1,
    SourceBindingQualityV1,
)
from app.services.reviews.quality_metrics import (
    CoverageObservation,
    aggregate_quality_summary,
    claim_hallucination_metric,
    claim_progress_metric,
    claim_quality,
    difficulty_adaptation_report,
    measured_coverage,
    ordinary_coverage_metric,
    ordinary_reference_metric,
    unmeasured_coverage,
)
from app.models.reviews.quality_metrics import DifficultyLabelResultV1


def _target(index: int, *, covered: bool = True) -> CoverageTargetV1:
    if covered:
        return CoverageTargetV1(
            target_id=f"node-{index}", display_name=f"节点{index}", status="covered",
            paragraph_id=f"p-{index}",
        )
    return CoverageTargetV1(
        target_id=f"node-{index}", display_name=f"节点{index}", status="missing",
        reason_code="TARGET_NOT_TAUGHT",
    )


def _summary(**overrides) -> ClaimMetricSummary:
    values = {
        "metric_status": ClaimMetricStatus.COMPLETE,
        "claim_hallucination_rate": 0.0,
        "claim_total": 10,
        "factual_claim_total": 10,
        "supported_claim_total": 10,
        "contradicted_claim_total": 0,
        "not_in_evidence_claim_total": 0,
        "non_factual_claim_total": 0,
        "incomplete_claim_total": 0,
    }
    values.update(overrides)
    return ClaimMetricSummary(**values)


def _item(*, coverage: RateMetricV1, claim: ClaimQualityV1 | None = None) -> ResourceQualityMetricsV1:
    claim = claim or claim_quality(_summary(), requested=True, status="complete")
    return ResourceQualityMetricsV1(
        run_id="run-1",
        resource_spec_id="spec-1",
        resource_id="res-1",
        resource_version=1,
        resource_type="讲义",
        coverage=coverage,
        hallucination=claim.hallucination,
        factual_support=claim.support_rate,
        claim=claim,
        ordinary_review={
            "status": "complete" if coverage.status is QualityMetricStatus.COMPLETE else "unavailable",
            "review_id": "rev-1",
            "target_total": coverage.denominator,
            "covered_target_total": coverage.numerator,
            "missing_target_total": (
                coverage.denominator - coverage.numerator
                if coverage.denominator is not None and coverage.numerator is not None else None
            ),
        },
        difficulty_fit=DifficultyFitV1(dimension_status="pass", estimated_difficulty="中级"),
        issue_statistics=IssueStatisticsV1(history_completeness="complete", open_issue_total=0),
        source_binding=SourceBindingQualityV1(),
        review_id="rev-1",
    )


# --- C01 ---------------------------------------------------------------
def test_coverage_counts_exactly_nine_of_ten_targets():
    targets = [_target(index, covered=index != 9) for index in range(10)]
    metric = measured_coverage(targets)
    assert metric.status is QualityMetricStatus.COMPLETE
    assert metric.source is QualityMetricSource.ORDINARY_REVIEW
    assert metric.definition_version == COVERAGE_DEFINITION_VERSION
    assert (metric.numerator, metric.denominator) == (9, 10)
    assert metric.value == pytest.approx(0.9)
    assert metric.assessment is QualityAssessment.MET


def test_duplicate_or_empty_target_results_are_rejected():
    with pytest.raises(ValueError):
        measured_coverage([_target(1), _target(1)])
    with pytest.raises(ValueError):
        measured_coverage([])


def test_empty_target_set_is_not_zero_or_one():
    metric = unmeasured_coverage(
        QualityMetricStatus.UNAVAILABLE, reason_codes=("COVERAGE_TARGETS_EMPTY",),
    )
    assert metric.value is None
    assert metric.numerator is None and metric.denominator is None


# --- C02 ---------------------------------------------------------------
def test_coverage_is_independent_of_claim_state():
    targets = [_target(index, covered=index < 3) for index in range(4)]
    coverage = measured_coverage(targets)
    with_claims = _item(coverage=coverage)
    without_claims = _item(
        coverage=coverage,
        claim=claim_quality(None, requested=False, status="not_requested"),
    )
    assert with_claims.coverage == without_claims.coverage
    assert with_claims.coverage.value == pytest.approx(0.75)


# --- C04 ---------------------------------------------------------------
def test_coverage_can_be_reported_even_when_another_dimension_fails():
    item = _item(coverage=measured_coverage([_target(1)]))
    failing = item.model_copy(update={
        "difficulty_fit": DifficultyFitV1(dimension_status="fail", estimated_difficulty="高级"),
    })
    assert failing.coverage.status is QualityMetricStatus.COMPLETE
    assert failing.difficulty_fit.dimension_status == "fail"


# --- H01 ---------------------------------------------------------------
def test_ordinary_reference_is_a_fixed_unassessed_rule_value():
    metric = ordinary_reference_metric()
    assert metric.value == ORDINARY_REFERENCE_VALUE == 0.05
    assert metric.status is QualityMetricStatus.REFERENCE
    assert metric.source is QualityMetricSource.ORDINARY_RULE_REFERENCE
    assert metric.assessment is QualityAssessment.NOT_ASSESSED
    assert metric.numerator is None and metric.denominator is None
    assert metric.definition_version == ORDINARY_REFERENCE_DEFINITION_VERSION
    assert metric.evidence_mode is QualityEvidenceMode.RULE_REFERENCE
    assert metric.threshold is None


def test_reference_cannot_fabricate_counts_or_claim_a_pass():
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.HALLUCINATION_RATE,
            definition_version=ORDINARY_REFERENCE_DEFINITION_VERSION,
            value=0.05, status=QualityMetricStatus.REFERENCE,
            source=QualityMetricSource.ORDINARY_RULE_REFERENCE,
            numerator=5, denominator=100, assessment=QualityAssessment.NOT_ASSESSED,
            evidence_mode=QualityEvidenceMode.RULE_REFERENCE,
        )
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.HALLUCINATION_RATE,
            definition_version=ORDINARY_REFERENCE_DEFINITION_VERSION,
            value=0.05, status=QualityMetricStatus.REFERENCE,
            source=QualityMetricSource.ORDINARY_RULE_REFERENCE,
            assessment=QualityAssessment.MET,
            evidence_mode=QualityEvidenceMode.RULE_REFERENCE,
        )


def test_only_the_hallucination_metric_may_use_the_reference_status():
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
            definition_version=COVERAGE_DEFINITION_VERSION,
            value=0.05, status=QualityMetricStatus.REFERENCE,
            source=QualityMetricSource.ORDINARY_RULE_REFERENCE,
            assessment=QualityAssessment.NOT_ASSESSED,
            evidence_mode=QualityEvidenceMode.RULE_REFERENCE,
        )


# --- H02 ---------------------------------------------------------------
def test_unrequested_claim_check_alone_is_not_a_reference():
    metric = claim_hallucination_metric(None, requested=False)
    assert metric.status is QualityMetricStatus.NOT_REQUESTED
    assert metric.value is None


# --- H03 ---------------------------------------------------------------
def test_real_five_percent_does_not_meet_the_strict_threshold():
    metric = claim_hallucination_metric(
        _summary(factual_claim_total=20, supported_claim_total=19,
                 contradicted_claim_total=1, claim_total=20),
        requested=True,
    )
    assert metric.value == pytest.approx(0.05)
    assert metric.assessment is QualityAssessment.NOT_MET
    assert (metric.numerator, metric.denominator) == (1, 20)


def test_four_percent_passes_and_zero_percent_passes():
    four = claim_hallucination_metric(
        _summary(factual_claim_total=100, supported_claim_total=96,
                 not_in_evidence_claim_total=4, claim_total=100),
        requested=True,
    )
    assert four.value == pytest.approx(0.04)
    assert four.assessment is QualityAssessment.MET
    zero = claim_hallucination_metric(_summary(), requested=True)
    assert zero.value == 0.0
    assert zero.assessment is QualityAssessment.MET


def test_claim_source_is_claim_judge_and_definition_is_fixed():
    metric = claim_hallucination_metric(_summary(), requested=True)
    assert metric.source is QualityMetricSource.CLAIM_JUDGE
    assert metric.definition_version == CLAIM_RISK_DEFINITION_VERSION


# --- H04 ---------------------------------------------------------------
@pytest.mark.parametrize(
    "status",
    ["incomplete", "failed", "not_applicable", "pending", "unavailable"],
)
def test_unfinished_claim_states_never_fall_back_to_five_percent(status):
    summary = _summary(metric_status=ClaimMetricStatus.INCOMPLETE,
                       claim_hallucination_rate=None, incomplete_claim_total=3,
                       supported_claim_total=7)
    metric = claim_hallucination_metric(
        summary, requested=True,
        failed=status == "failed", pending=status == "pending",
        not_applicable=status == "not_applicable",
    )
    assert metric.value is None
    assert metric.status is not QualityMetricStatus.REFERENCE
    assert metric.assessment in {QualityAssessment.NOT_ASSESSED, QualityAssessment.NOT_APPLICABLE}


def test_no_factual_claims_is_not_applicable_without_a_zero_rate():
    metric = claim_hallucination_metric(
        _summary(metric_status=ClaimMetricStatus.NOT_APPLICABLE, claim_hallucination_rate=0.0,
                 claim_total=2, factual_claim_total=0, supported_claim_total=0,
                 non_factual_claim_total=2),
        requested=True,
    )
    assert metric.status is QualityMetricStatus.NOT_APPLICABLE
    assert metric.value is None


# --- H05 ---------------------------------------------------------------
def test_failure_sentinel_does_not_produce_a_negative_progress():
    summary = _summary(metric_status=ClaimMetricStatus.INCOMPLETE, claim_hallucination_rate=None,
                       claim_total=0, factual_claim_total=0, supported_claim_total=0,
                       incomplete_claim_total=1)
    progress = claim_progress_metric(summary, requested=True)
    assert progress.value is None
    assert progress.status is QualityMetricStatus.NOT_APPLICABLE


def test_partial_progress_is_a_real_ratio():
    summary = _summary(factual_claim_total=10, supported_claim_total=6,
                       incomplete_claim_total=4)
    progress = claim_progress_metric(summary, requested=True)
    assert progress.value == pytest.approx(0.6)
    assert (progress.numerator, progress.denominator) == (6, 10)


# --- Source isolation --------------------------------------------------
def test_claim_source_cannot_supply_core_coverage():
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
            definition_version=COVERAGE_DEFINITION_VERSION,
            value=1.0, status=QualityMetricStatus.COMPLETE,
            source=QualityMetricSource.CLAIM_JUDGE,
            numerator=1, denominator=1,
            assessment=QualityAssessment.MET,
            evidence_mode=QualityEvidenceMode.PRODUCTION_AUDIT,
        )


def test_complete_metric_must_match_its_counts():
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
            definition_version=COVERAGE_DEFINITION_VERSION,
            value=0.5, status=QualityMetricStatus.COMPLETE,
            source=QualityMetricSource.ORDINARY_REVIEW,
            numerator=9, denominator=10,
            assessment=QualityAssessment.NOT_MET,
            evidence_mode=QualityEvidenceMode.PRODUCTION_AUDIT,
        )


def test_negative_or_inverted_counts_are_rejected():
    with pytest.raises(ValidationError):
        RateMetricV1(
            metric_id=QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
            definition_version=COVERAGE_DEFINITION_VERSION,
            value=1.0, status=QualityMetricStatus.COMPLETE,
            source=QualityMetricSource.ORDINARY_REVIEW,
            numerator=11, denominator=10,
            assessment=QualityAssessment.MET,
            evidence_mode=QualityEvidenceMode.PRODUCTION_AUDIT,
        )


# --- A01 ---------------------------------------------------------------
def test_reference_and_verified_subset_are_never_averaged():
    verified = claim_quality(
        _summary(factual_claim_total=50, supported_claim_total=49,
                 contradicted_claim_total=1, claim_total=50),
        requested=True, status="complete",
    )
    reference = claim_quality(None, requested=False, status="reference")
    assert reference.hallucination.value == 0.05
    items = [
        _item(coverage=measured_coverage([_target(1)]), claim=verified),
        _item(coverage=measured_coverage([_target(2)]), claim=reference),
    ]
    summary = aggregate_quality_summary(items)
    assert summary.claim_verified_resource_total == 1
    assert summary.reference_resource_total == 1
    assert summary.reference_value == 0.05
    assert summary.claim_unverified_subset_rate is not None
    assert summary.claim_unverified_subset_rate.value == pytest.approx(0.02)
    assert summary.claim_unverified_subset_rate.assessment is QualityAssessment.NOT_ASSESSED
    assert "VERIFIED_SUBSET_ONLY" in summary.claim_unverified_subset_rate.reason_codes


# --- A02 ---------------------------------------------------------------
def test_coverage_aggregates_resource_targets_not_percentages():
    items = [
        _item(coverage=measured_coverage([_target(0), _target(1)])),
        _item(coverage=measured_coverage([
            _target(0), _target(1, covered=False), _target(2, covered=False),
            _target(3, covered=False), _target(4, covered=False), _target(5, covered=False),
            _target(6, covered=False), _target(7, covered=False),
        ])),
    ]
    summary = aggregate_quality_summary(items)
    assert summary.coverage.status is QualityMetricStatus.COMPLETE
    assert (summary.coverage.numerator, summary.coverage.denominator) == (3, 10)
    assert summary.coverage.value == pytest.approx(0.3)


def test_missing_resource_result_makes_the_aggregate_incomplete():
    items = [
        _item(coverage=measured_coverage([_target(0), _target(1)])),
        _item(coverage=unmeasured_coverage(
            QualityMetricStatus.UNAVAILABLE, reason_codes=("COVERAGE_TARGETS_EMPTY",),
        )),
    ]
    # Keep the claim buckets consistent with the contract before asserting.
    items[1] = items[1].model_copy(update={
        "ordinary_review": items[1].ordinary_review.model_copy(update={"review_id": "rev-1"}),
    })
    summary = aggregate_quality_summary(items)
    assert summary.coverage.status is QualityMetricStatus.INCOMPLETE
    assert summary.coverage.value is None
    assert summary.coverage_covered_target_total == 2
    assert summary.coverage_unknown_resource_total == 1


# --- E03 ---------------------------------------------------------------
def test_difficulty_accuracy_uses_labelled_cases_only():
    results = [DifficultyLabelResultV1(case_id=f"c{index}", expected_label="初级",
                                       predicted_label="初级" if index < 85 else "中级")
               for index in range(100)]
    report = difficulty_adaptation_report(
        results, planned_case_total=100, fixture_version="v1",
        evidence_mode=QualityEvidenceMode.OFFLINE_GOLD,
    )
    assert report.metric.value == pytest.approx(0.85)
    assert report.metric.assessment is QualityAssessment.MET
    assert report.metric.definition_version == DIFFICULTY_ACCURACY_DEFINITION_VERSION
    assert report.metric.source is QualityMetricSource.LABELED_EVALUATION
    assert report.confusion_matrix["初级"]["中级"] == 15


def test_no_labelled_cases_means_no_accuracy():
    report = difficulty_adaptation_report(
        [], planned_case_total=0, fixture_version="v1",
        evidence_mode=QualityEvidenceMode.OFFLINE_GOLD,
    )
    assert report.metric.value is None
    assert report.metric.status is QualityMetricStatus.UNAVAILABLE


def test_missing_evaluation_cases_keep_the_denominator():
    results = [DifficultyLabelResultV1(case_id="c1", expected_label="初级", predicted_label="初级")]
    report = difficulty_adaptation_report(
        results, planned_case_total=4, fixture_version="v1",
        evidence_mode=QualityEvidenceMode.LIVE_MODEL,
    )
    assert report.metric.value is None
    assert report.metric.status is QualityMetricStatus.INCOMPLETE
    assert report.planned_case_total == 4


# --- E01 ---------------------------------------------------------------
def test_competition_coverage_removes_claim_knowledge_points():
    observations = [
        CoverageObservation(case_id="c1", target_id="n1", covered=True),
        CoverageObservation(case_id="c1", target_id="n2", covered=False),
    ]
    metric = ordinary_coverage_metric(
        observations, planned_units=2, evidence_mode=QualityEvidenceMode.OFFLINE_GOLD,
    )
    assert metric.value == pytest.approx(0.5)
    assert metric.source is QualityMetricSource.ORDINARY_REVIEW
    assert metric.definition_version == COVERAGE_DEFINITION_VERSION


def test_competition_coverage_counts_a_missing_unit_per_case():
    observations = [
        CoverageObservation(case_id="c1", target_id="n1", covered=True),
        CoverageObservation(case_id="c2", target_id="n1", covered=False),
    ]
    metric = ordinary_coverage_metric(
        observations, planned_units=2, evidence_mode=QualityEvidenceMode.OFFLINE_GOLD,
    )
    assert metric.value == pytest.approx(0.5)
