"""The single pure calculation entry point for resource quality metrics (T48).

No IO happens here.  Services pass already-read facts and receive validated
``RateMetricV1`` / summary contracts.  Reporting, the run quality endpoint and
the competition evaluation all call these functions, so the three core metrics
cannot drift into several implementations.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.models.reviews.claims import ClaimMetricStatus, ClaimMetricSummary
from app.models.reviews.quality_metrics import (
    CLAIM_RISK_DEFINITION_VERSION,
    COVERAGE_DEFINITION_VERSION,
    DIFFICULTY_ACCURACY_DEFINITION_VERSION,
    ORDINARY_REFERENCE_DEFINITION_VERSION,
    ORDINARY_REFERENCE_VALUE,
    QUALITY_THRESHOLDS,
    ClaimMetricCountsV1,
    ClaimQualityV1,
    ClaimStatusBucketsV1,
    CoverageStatusBucketsV1,
    CoverageTargetV1,
    DifficultyAdaptationReportV1,
    DifficultyLabelResultV1,
    OrdinaryCoverageCaseV1,
    OrdinaryCoverageEvaluationV1,
    QualityAssessment,
    QualityAvailability,
    QualityEvidenceMode,
    QualityMetricId,
    QualityMetricSource,
    QualityMetricStatus,
    RateMetricV1,
    ResourceQualityMetricsV1,
    ResourceQualitySummaryV1,
    assess_value,
)


def _metric(
    metric_id: QualityMetricId,
    *,
    definition_version: str,
    status: QualityMetricStatus,
    source: QualityMetricSource,
    assessment: QualityAssessment,
    evidence_mode: QualityEvidenceMode,
    value: float | None = None,
    numerator: int | None = None,
    denominator: int | None = None,
    reason_codes: Sequence[str] = (),
    threshold: bool = True,
) -> RateMetricV1:
    return RateMetricV1(
        metric_id=metric_id,
        definition_version=definition_version,
        value=value,
        status=status,
        source=source,
        numerator=numerator,
        denominator=denominator,
        assessment=assessment,
        threshold=QUALITY_THRESHOLDS.get(metric_id) if threshold else None,
        evidence_mode=evidence_mode,
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def unmeasured_coverage(
    status: QualityMetricStatus,
    *,
    reason_codes: Sequence[str] = (),
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
) -> RateMetricV1:
    """A coverage metric without real per-target results: value stays null."""
    if status in {QualityMetricStatus.COMPLETE, QualityMetricStatus.REFERENCE}:
        raise ValueError("unmeasured coverage cannot claim a measurement")
    return _metric(
        QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
        definition_version=COVERAGE_DEFINITION_VERSION,
        status=status,
        source=QualityMetricSource.NONE,
        assessment=(
            QualityAssessment.NOT_APPLICABLE
            if status is QualityMetricStatus.NOT_APPLICABLE
            else QualityAssessment.NOT_ASSESSED
        ),
        evidence_mode=evidence_mode,
        reason_codes=reason_codes,
    )


def measured_coverage(
    targets: Sequence[CoverageTargetV1],
    *,
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
) -> RateMetricV1:
    """Covered frozen targets / frozen targets.  An empty set is never 0/0 or 100%."""
    if not targets:
        raise ValueError("coverage requires at least one frozen target result")
    ids = [item.target_id for item in targets]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate frozen target result")
    covered = sum(item.status == "covered" for item in targets)
    return _metric(
        QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
        definition_version=COVERAGE_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.ORDINARY_REVIEW,
        assessment=assess_value(
            QualityMetricId.CORE_KNOWLEDGE_COVERAGE, covered / len(targets),
        ),
        evidence_mode=evidence_mode,
        value=covered / len(targets),
        numerator=covered,
        denominator=len(targets),
    )


def ordinary_reference_metric(*, reason_codes: Sequence[str] = ()) -> RateMetricV1:
    """The fixed 5% ordinary-review rule reference (never a measurement)."""
    codes = set(reason_codes) | {"ORDINARY_RULE_REFERENCE_NOT_CALIBRATED"}
    return RateMetricV1(
        metric_id=QualityMetricId.HALLUCINATION_RATE,
        definition_version=ORDINARY_REFERENCE_DEFINITION_VERSION,
        value=ORDINARY_REFERENCE_VALUE,
        status=QualityMetricStatus.REFERENCE,
        source=QualityMetricSource.ORDINARY_RULE_REFERENCE,
        numerator=None,
        denominator=None,
        assessment=QualityAssessment.NOT_ASSESSED,
        threshold=None,
        evidence_mode=QualityEvidenceMode.RULE_REFERENCE,
        reason_codes=tuple(sorted(codes)),
    )


def claim_hallucination_metric(
    summary: ClaimMetricSummary | None,
    *,
    requested: bool,
    failed: bool = False,
    pending: bool = False,
    not_applicable: bool = False,
    conflict: bool = False,
    failure_code: str | None = None,
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
) -> RateMetricV1:
    """Claim risk rate, keeping unmeasured states distinct from 0% and from 5%."""

    def build(status: QualityMetricStatus, codes: Sequence[str]) -> RateMetricV1:
        return _metric(
            QualityMetricId.HALLUCINATION_RATE,
            definition_version=CLAIM_RISK_DEFINITION_VERSION,
            status=status,
            source=QualityMetricSource.NONE,
            assessment=(
                QualityAssessment.NOT_APPLICABLE
                if status is QualityMetricStatus.NOT_APPLICABLE
                else QualityAssessment.NOT_ASSESSED
            ),
            evidence_mode=evidence_mode,
            reason_codes=tuple(codes) + ((failure_code,) if failure_code else ()),
        )

    if not requested:
        return build(QualityMetricStatus.NOT_REQUESTED, ("CLAIM_CHECK_NOT_REQUESTED",))
    if failed:
        return build(QualityMetricStatus.FAILED, ("CLAIM_AUDIT_FAILED",))
    if pending:
        return build(QualityMetricStatus.PENDING, ("CLAIM_AUDIT_PENDING",))
    if not_applicable:
        return build(QualityMetricStatus.NOT_APPLICABLE, ("CLAIM_CHECK_NOT_APPLICABLE",))
    if conflict:
        return build(QualityMetricStatus.INCOMPLETE, ("CLAIM_JUDGEMENT_CONFLICT",))
    if summary is None:
        return build(QualityMetricStatus.UNAVAILABLE, ("CLAIM_FACTS_UNAVAILABLE",))
    if summary.metric_status is ClaimMetricStatus.INCOMPLETE:
        return build(QualityMetricStatus.INCOMPLETE, ("CLAIM_JUDGEMENT_INCOMPLETE",))
    if summary.metric_status is ClaimMetricStatus.NOT_APPLICABLE or summary.factual_claim_total == 0:
        return build(QualityMetricStatus.NOT_APPLICABLE, ("NO_FACTUAL_CLAIMS",))
    risk = summary.contradicted_claim_total + summary.not_in_evidence_claim_total
    value = risk / summary.factual_claim_total
    return _metric(
        QualityMetricId.HALLUCINATION_RATE,
        definition_version=CLAIM_RISK_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.CLAIM_JUDGE,
        assessment=assess_value(QualityMetricId.HALLUCINATION_RATE, value),
        evidence_mode=evidence_mode,
        value=value,
        numerator=risk,
        denominator=summary.factual_claim_total,
    )


def claim_support_metric(
    summary: ClaimMetricSummary | None,
    *,
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
) -> RateMetricV1 | None:
    """Supported / factual inside the same measured set; never an extra score."""
    if summary is None or summary.metric_status is not ClaimMetricStatus.COMPLETE:
        return None
    if summary.factual_claim_total <= 0:
        return None
    return _metric(
        QualityMetricId.FACTUAL_SUPPORT_RATE,
        definition_version=CLAIM_RISK_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.CLAIM_JUDGE,
        assessment=assess_value(
            QualityMetricId.FACTUAL_SUPPORT_RATE,
            summary.supported_claim_total / summary.factual_claim_total,
        ),
        evidence_mode=evidence_mode,
        value=summary.supported_claim_total / summary.factual_claim_total,
        numerator=summary.supported_claim_total,
        denominator=summary.factual_claim_total,
        threshold=False,
    )


def claim_progress_metric(
    summary: ClaimMetricSummary | None,
    *,
    requested: bool,
    failed: bool = False,
    pending: bool = False,
    failure_code: str | None = None,
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
) -> RateMetricV1:
    """Verified share of the extracted factual set; never negative."""

    def empty(status: QualityMetricStatus, code: str) -> RateMetricV1:
        return _metric(
            QualityMetricId.CLAIM_CHECK_PROGRESS,
            definition_version=CLAIM_RISK_DEFINITION_VERSION,
            status=status,
            source=QualityMetricSource.NONE,
            assessment=(
                QualityAssessment.NOT_APPLICABLE
                if status is QualityMetricStatus.NOT_APPLICABLE
                else QualityAssessment.NOT_ASSESSED
            ),
            evidence_mode=evidence_mode,
            reason_codes=(code,) + ((failure_code,) if failure_code else ()),
            threshold=False,
        )

    if not requested:
        return empty(QualityMetricStatus.NOT_REQUESTED, "CLAIM_CHECK_NOT_REQUESTED")
    if failed:
        return empty(QualityMetricStatus.FAILED, "CLAIM_AUDIT_FAILED")
    if pending:
        return empty(QualityMetricStatus.PENDING, "CLAIM_AUDIT_PENDING")
    if summary is None:
        return empty(QualityMetricStatus.UNAVAILABLE, "CLAIM_FACTS_UNAVAILABLE")
    if summary.factual_claim_total <= 0:
        return empty(QualityMetricStatus.NOT_APPLICABLE, "NO_FACTUAL_CLAIMS")
    if summary.incomplete_claim_total > summary.factual_claim_total:
        return empty(QualityMetricStatus.UNAVAILABLE, "CLAIM_COUNTS_INCONSISTENT")
    verified = summary.factual_claim_total - summary.incomplete_claim_total
    return _metric(
        QualityMetricId.CLAIM_CHECK_PROGRESS,
        definition_version=CLAIM_RISK_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.CLAIM_JUDGE,
        assessment=assess_value(QualityMetricId.CLAIM_CHECK_PROGRESS, verified / summary.factual_claim_total),
        evidence_mode=evidence_mode,
        value=verified / summary.factual_claim_total,
        numerator=verified,
        denominator=summary.factual_claim_total,
        threshold=False,
    )


def claim_counts(summary: ClaimMetricSummary) -> ClaimMetricCountsV1:
    return ClaimMetricCountsV1(
        claim_total=summary.claim_total,
        factual_claim_total=summary.factual_claim_total,
        supported_claim_total=summary.supported_claim_total,
        contradicted_claim_total=summary.contradicted_claim_total,
        not_in_evidence_claim_total=summary.not_in_evidence_claim_total,
        non_factual_claim_total=summary.non_factual_claim_total,
        incomplete_claim_total=summary.incomplete_claim_total,
    )


def claim_quality(
    summary: ClaimMetricSummary | None,
    *,
    requested: bool,
    status: str,
    review_id: str | None = None,
    failed: bool = False,
    pending: bool = False,
    not_applicable: bool = False,
    conflict: bool = False,
    failure_code: str | None = None,
    evidence_mode: QualityEvidenceMode = QualityEvidenceMode.PRODUCTION_AUDIT,
    reason_codes: Sequence[str] = (),
) -> ClaimQualityV1:
    hallucination = (
        ordinary_reference_metric(reason_codes=reason_codes)
        if status == "reference"
        else claim_hallucination_metric(
            summary, requested=requested, failed=failed, pending=pending,
            not_applicable=not_applicable, conflict=conflict, failure_code=failure_code,
            evidence_mode=evidence_mode,
        )
    )
    if status not in {"complete", "reference"}:
        state = QualityMetricStatus(status)
        hallucination = _metric(
            QualityMetricId.HALLUCINATION_RATE,
            definition_version=CLAIM_RISK_DEFINITION_VERSION, status=state,
            source=QualityMetricSource.NONE, evidence_mode=evidence_mode,
            assessment=(QualityAssessment.NOT_APPLICABLE
                        if state is QualityMetricStatus.NOT_APPLICABLE
                        else QualityAssessment.NOT_ASSESSED),
            reason_codes=tuple(reason_codes) + ((failure_code,) if failure_code else ()),
        )
    progress = claim_progress_metric(
        summary, requested=requested, failed=failed, pending=pending,
        failure_code=failure_code, evidence_mode=evidence_mode,
    )
    if status not in {"complete", "reference", "not_requested"} and not (
        status == "incomplete" and summary is not None and not conflict
    ):
        progress = _metric(
            QualityMetricId.CLAIM_CHECK_PROGRESS,
            definition_version=CLAIM_RISK_DEFINITION_VERSION,
            status=QualityMetricStatus(status), source=QualityMetricSource.NONE,
            assessment=(QualityAssessment.NOT_APPLICABLE if status == "not_applicable"
                        else QualityAssessment.NOT_ASSESSED),
            evidence_mode=evidence_mode, threshold=False,
            reason_codes=tuple(reason_codes) + ((failure_code,) if failure_code else ()),
        )
    return ClaimQualityV1(
        requested=requested,
        status=status,
        review_id=review_id,
        counts=claim_counts(summary) if status == "complete" and summary is not None else None,
        hallucination=hallucination,
        support_rate=claim_support_metric(summary, evidence_mode=evidence_mode) if status == "complete" else None,
        progress=progress,
        failure_code=failure_code,
        reason_codes=tuple(sorted(set(reason_codes))),
    )


def aggregate_quality_summary(
    items: Sequence[ResourceQualityMetricsV1],
) -> ResourceQualitySummaryV1:
    """Resource-target aggregation; a partial sample never becomes a full rate."""
    total = len(items)
    measured = [item for item in items if item.coverage.status is QualityMetricStatus.COMPLETE]
    known_targets = 0
    known_covered = 0
    for item in measured:
        known_targets += item.coverage.denominator or 0
        known_covered += item.coverage.numerator or 0
    unknown = total - len(measured)
    if total and not unknown and known_targets:
        coverage = measured_coverage_from_counts(known_covered, known_targets)
        codes: list[str] = []
    elif total:
        coverage = unmeasured_coverage(
            QualityMetricStatus.INCOMPLETE,
            reason_codes=("COVERAGE_RESULT_INCOMPLETE",),
        )
        codes = ["COVERAGE_RESULT_INCOMPLETE"]
    else:
        coverage = unmeasured_coverage(
            QualityMetricStatus.NOT_APPLICABLE, reason_codes=("NO_VISIBLE_RESOURCES",),
        )
        codes = ["NO_VISIBLE_RESOURCES"]

    verified = [item for item in items if item.claim.status == "complete" and item.claim.counts]
    risk = sum(item.claim.counts.contradicted_claim_total + item.claim.counts.not_in_evidence_claim_total
               for item in verified)
    factual = sum(item.claim.counts.factual_claim_total for item in verified)
    subset_rate = None
    if factual > 0:
        subset_only = len(verified) < total
        subset_rate = _metric(
            QualityMetricId.HALLUCINATION_RATE,
            definition_version=CLAIM_RISK_DEFINITION_VERSION,
            status=QualityMetricStatus.COMPLETE,
            source=QualityMetricSource.CLAIM_JUDGE,
            assessment=(
                QualityAssessment.NOT_ASSESSED if subset_only
                else assess_value(QualityMetricId.HALLUCINATION_RATE, risk / factual)
            ),
            evidence_mode=QualityEvidenceMode.PRODUCTION_AUDIT,
            value=risk / factual,
            numerator=risk,
            denominator=factual,
            reason_codes=("VERIFIED_SUBSET_ONLY",) if subset_only else (),
        )

    coverage_buckets = CoverageStatusBucketsV1(**{
        status.value: sum(item.coverage.status is status for item in items)
        for status in (
            QualityMetricStatus.COMPLETE, QualityMetricStatus.PENDING,
            QualityMetricStatus.INCOMPLETE, QualityMetricStatus.FAILED,
            QualityMetricStatus.NOT_REQUESTED, QualityMetricStatus.NOT_APPLICABLE,
            QualityMetricStatus.UNAVAILABLE, QualityMetricStatus.LEGACY_UNAVAILABLE,
        )
    })
    claim_buckets = ClaimStatusBucketsV1(**{
        status.value: sum(item.hallucination.status is status for item in items)
        for status in (
            QualityMetricStatus.COMPLETE, QualityMetricStatus.REFERENCE,
            QualityMetricStatus.PENDING, QualityMetricStatus.INCOMPLETE,
            QualityMetricStatus.FAILED, QualityMetricStatus.NOT_REQUESTED,
            QualityMetricStatus.NOT_APPLICABLE, QualityMetricStatus.UNAVAILABLE,
            QualityMetricStatus.LEGACY_UNAVAILABLE,
        )
    })
    return ResourceQualitySummaryV1(
        resource_total=total,
        coverage=coverage,
        coverage_buckets=coverage_buckets,
        coverage_target_total=known_targets if measured else None,
        coverage_covered_target_total=known_covered if measured else None,
        coverage_missing_target_total=(known_targets - known_covered) if measured else None,
        coverage_unknown_resource_total=unknown,
        claim_buckets=claim_buckets,
        claim_verified_resource_total=len(verified),
        claim_risk_fact_total=risk,
        claim_factual_total=factual,
        claim_unverified_subset_rate=subset_rate,
        reference_resource_total=claim_buckets.reference,
        reference_value=(
            ORDINARY_REFERENCE_VALUE if claim_buckets.reference else None
        ),
        reason_codes=tuple(sorted(set(codes))),
    )


def measured_coverage_from_counts(covered: int, targets: int) -> RateMetricV1:
    if targets <= 0:
        raise ValueError("aggregate coverage requires a positive target total")
    if covered > targets:
        raise ValueError("covered cannot exceed the target total")
    return _metric(
        QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
        definition_version=COVERAGE_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.ORDINARY_REVIEW,
        assessment=assess_value(
            QualityMetricId.CORE_KNOWLEDGE_COVERAGE, covered / targets,
        ),
        evidence_mode=QualityEvidenceMode.PRODUCTION_AUDIT,
        value=covered / targets,
        numerator=covered,
        denominator=targets,
    )


def difficulty_adaptation_report(
    results: Sequence[DifficultyLabelResultV1],
    *,
    planned_case_total: int,
    fixture_version: str,
    evidence_mode: QualityEvidenceMode,
) -> DifficultyAdaptationReportV1:
    """Accuracy over all selected labelled cases; failures stay in the denominator."""
    if planned_case_total < 0:
        raise ValueError("planned_case_total cannot be negative")
    labels = sorted({value for item in results for value in (item.expected_label, item.predicted_label)})
    matrix = {expected: {predicted: 0 for predicted in labels} for expected in labels}
    correct = 0
    for item in results:
        matrix[item.expected_label][item.predicted_label] += 1
        correct += item.expected_label == item.predicted_label
    by_case = {item.case_id for item in results}
    if planned_case_total == 0 or len(by_case) != len(results):
        metric = _metric(
            QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY,
            definition_version=DIFFICULTY_ACCURACY_DEFINITION_VERSION,
            status=QualityMetricStatus.UNAVAILABLE,
            source=QualityMetricSource.NONE,
            assessment=QualityAssessment.NOT_ASSESSED,
            evidence_mode=evidence_mode,
            reason_codes=("NO_LABELLED_EVALUATION_CASES",),
        )
    elif len(results) < planned_case_total:
        metric = _metric(
            QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY,
            definition_version=DIFFICULTY_ACCURACY_DEFINITION_VERSION,
            status=QualityMetricStatus.INCOMPLETE,
            source=QualityMetricSource.NONE,
            assessment=QualityAssessment.NOT_ASSESSED,
            evidence_mode=evidence_mode,
            reason_codes=("EVALUATION_CASES_MISSING",),
        )
    else:
        accuracy = correct / planned_case_total
        metric = _metric(
            QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY,
            definition_version=DIFFICULTY_ACCURACY_DEFINITION_VERSION,
            status=QualityMetricStatus.COMPLETE,
            source=QualityMetricSource.LABELED_EVALUATION,
            assessment=assess_value(QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY, accuracy),
            evidence_mode=evidence_mode,
            value=accuracy,
            numerator=correct,
            denominator=planned_case_total,
        )
    return DifficultyAdaptationReportV1(
        metric=metric,
        fixture_version=fixture_version,
        evidence_mode=evidence_mode,
        planned_case_total=planned_case_total,
        correct_case_total=correct,
        labels=tuple(labels),
        confusion_matrix=matrix,
    )


@dataclass(frozen=True)
class CoverageObservation:
    """One ``(case_id, target_id)`` unit of the competition coverage definition."""

    case_id: str
    target_id: str
    covered: bool


def ordinary_coverage_metric(
    observations: Sequence[CoverageObservation],
    *,
    planned_units: int,
    evidence_mode: QualityEvidenceMode,
    missing_case_total: int = 0,
    complete: bool = True,
) -> RateMetricV1:
    """Competition coverage: covered ``(case_id, target_id)`` units / planned units."""
    covered = sum(item.covered for item in observations)
    if planned_units <= 0:
        return unmeasured_coverage(
            QualityMetricStatus.NOT_APPLICABLE,
            reason_codes=("NO_FROZEN_TARGETS",),
            evidence_mode=evidence_mode,
        )
    if covered > planned_units:
        raise ValueError("covered units cannot exceed planned units")
    if not complete or len({(item.case_id, item.target_id) for item in observations}) < planned_units:
        return _metric(
            QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
            definition_version=COVERAGE_DEFINITION_VERSION,
            status=QualityMetricStatus.INCOMPLETE,
            source=QualityMetricSource.NONE,
            assessment=QualityAssessment.NOT_ASSESSED,
            evidence_mode=evidence_mode,
            reason_codes=("COVERAGE_UNITS_MISSING",) + (
                ("EVALUATION_CASES_MISSING",) if missing_case_total else ()
            ),
        )
    return _metric(
        QualityMetricId.CORE_KNOWLEDGE_COVERAGE,
        definition_version=COVERAGE_DEFINITION_VERSION,
        status=QualityMetricStatus.COMPLETE,
        source=QualityMetricSource.ORDINARY_REVIEW,
        assessment=assess_value(
            QualityMetricId.CORE_KNOWLEDGE_COVERAGE, covered / planned_units,
        ),
        evidence_mode=evidence_mode,
        value=covered / planned_units,
        numerator=covered,
        denominator=planned_units,
    )


def ordinary_coverage_evaluation(
    cases: Sequence[OrdinaryCoverageCaseV1],
    *,
    planned_case_total: int,
    planned_unit_total: int,
    fixture_version: str,
    evidence_mode: QualityEvidenceMode,
) -> OrdinaryCoverageEvaluationV1:
    """Assemble the competition coverage report from per-case unit results."""
    observations = [
        CoverageObservation(case_id=case.case_id, target_id=target.target_id, covered=target.covered)
        for case in cases if case.observed
        for target in case.targets
    ]
    observed_total = sum(case.observed for case in cases)
    failed_total = sum(case.failure_code is not None for case in cases)
    missing = max(0, planned_case_total - observed_total)
    solved_units = len({(item.case_id, item.target_id) for item in observations})
    complete = (
        observed_total == planned_case_total
        and planned_unit_total > 0
        and solved_units == planned_unit_total
    )
    metric = ordinary_coverage_metric(
        observations,
        planned_units=planned_unit_total,
        evidence_mode=evidence_mode,
        missing_case_total=missing,
        complete=complete,
    )
    covered = sum(item.covered for item in observations)
    return OrdinaryCoverageEvaluationV1(
        coverage_fixture_version=fixture_version,
        evidence_mode=evidence_mode,
        planned_case_total=planned_case_total,
        observed_case_total=observed_total,
        failed_case_total=failed_total,
        missing_case_count=missing,
        planned_unit_total=planned_unit_total,
        covered_unit_total=covered,
        missing_unit_total=(planned_unit_total - covered) if complete else None,
        unknown_case_ids=tuple(sorted(case.case_id for case in cases if not case.observed)),
        metric=metric,
        cases=tuple(sorted(cases, key=lambda item: item.case_id)),
    )


def availability_for(items: Sequence[ResourceQualityMetricsV1]) -> QualityAvailability:
    if not items:
        return QualityAvailability.UNAVAILABLE
    measured = sum(item.availability is QualityAvailability.AVAILABLE for item in items)
    if measured == len(items):
        return QualityAvailability.AVAILABLE
    return QualityAvailability.PARTIAL if measured else QualityAvailability.UNAVAILABLE


__all__ = [
    "CoverageObservation",
    "aggregate_quality_summary",
    "availability_for",
    "claim_counts",
    "claim_hallucination_metric",
    "claim_progress_metric",
    "claim_quality",
    "claim_support_metric",
    "difficulty_adaptation_report",
    "measured_coverage",
    "measured_coverage_from_counts",
    "ordinary_coverage_evaluation",
    "ordinary_coverage_metric",
    "ordinary_reference_metric",
    "unmeasured_coverage",
]
