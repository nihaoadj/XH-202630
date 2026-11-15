"""Versioned, public quality-metric contract (T48).

This module is a pure contract: it must not import API, Service, repository,
agent or settings modules.  Every ratio is expressed in ``0..1``; the frontend
formats percentages.  ``value=None`` means "no externally explainable number"
and is never a stand-in for zero.

Two rules are load-bearing and validated here rather than in callers:

* 核心知识点覆盖率 may only come from the ordinary review
  (``ordinary_review`` / ``ordinary_review`` source).  A Claim-derived coverage
  projection is rejected instead of being silently accepted as the same metric.
* The 5% ordinary-review reference is a fixed rule value, not a measurement.  It
  must carry ``status=reference``, no numerator/denominator and
  ``assessment=not_assessed`` so it can never be compared as a real rate.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


METRIC_POLICY_VERSION = "resource-quality/v2"
COVERAGE_DEFINITION_VERSION = "ordinary-target-coverage/v2"
CLAIM_RISK_DEFINITION_VERSION = "claim-risk/v1"
ORDINARY_REFERENCE_DEFINITION_VERSION = "ordinary-approved-reference/v1"
DIFFICULTY_ACCURACY_DEFINITION_VERSION = "difficulty-label-accuracy/v1"
ORDINARY_REFERENCE_VALUE = 0.05
QUALITY_SCHEMA_VERSION = "1.0"

_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


class QualityMetricId(str, Enum):
    CORE_KNOWLEDGE_COVERAGE = "core_knowledge_coverage"
    HALLUCINATION_RATE = "hallucination_rate"
    FACTUAL_SUPPORT_RATE = "factual_support_rate"
    DIFFICULTY_ADAPTATION_ACCURACY = "difficulty_adaptation_accuracy"
    CLAIM_CHECK_PROGRESS = "claim_check_progress"


class QualityMetricStatus(str, Enum):
    COMPLETE = "complete"
    REFERENCE = "reference"
    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    INCOMPLETE = "incomplete"
    FAILED = "failed"
    NOT_APPLICABLE = "not_applicable"
    LEGACY_UNAVAILABLE = "legacy_unavailable"
    UNAVAILABLE = "unavailable"


class QualityMetricSource(str, Enum):
    ORDINARY_REVIEW = "ordinary_review"
    ORDINARY_RULE_REFERENCE = "ordinary_rule_reference"
    CLAIM_JUDGE = "claim_judge"
    LABELED_EVALUATION = "labeled_evaluation"
    NONE = "none"


class QualityAssessment(str, Enum):
    MET = "met"
    NOT_MET = "not_met"
    NOT_ASSESSED = "not_assessed"
    NOT_APPLICABLE = "not_applicable"


class ThresholdComparator(str, Enum):
    LT = "lt"
    GTE = "gte"


class QualityEvidenceMode(str, Enum):
    PRODUCTION_AUDIT = "production_audit"
    OFFLINE_GOLD = "offline_gold"
    LIVE_MODEL = "live_model"
    RULE_REFERENCE = "rule_reference"
    LEGACY = "legacy"


class QualityAvailability(str, Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


DEFINITION_VERSIONS = {
    QualityMetricId.CORE_KNOWLEDGE_COVERAGE: COVERAGE_DEFINITION_VERSION,
    QualityMetricId.HALLUCINATION_RATE: CLAIM_RISK_DEFINITION_VERSION,
    QualityMetricId.FACTUAL_SUPPORT_RATE: CLAIM_RISK_DEFINITION_VERSION,
    QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY: DIFFICULTY_ACCURACY_DEFINITION_VERSION,
    QualityMetricId.CLAIM_CHECK_PROGRESS: CLAIM_RISK_DEFINITION_VERSION,
}

_NULL_STATUSES = frozenset({
    QualityMetricStatus.NOT_REQUESTED,
    QualityMetricStatus.PENDING,
    QualityMetricStatus.INCOMPLETE,
    QualityMetricStatus.FAILED,
    QualityMetricStatus.NOT_APPLICABLE,
    QualityMetricStatus.LEGACY_UNAVAILABLE,
    QualityMetricStatus.UNAVAILABLE,
})

_MEASUREMENT_SOURCES = frozenset({
    QualityMetricSource.ORDINARY_REVIEW,
    QualityMetricSource.CLAIM_JUDGE,
    QualityMetricSource.LABELED_EVALUATION,
})

_METRIC_SOURCES = {
    QualityMetricId.CORE_KNOWLEDGE_COVERAGE: frozenset({QualityMetricSource.ORDINARY_REVIEW}),
    QualityMetricId.HALLUCINATION_RATE: frozenset({
        QualityMetricSource.CLAIM_JUDGE, QualityMetricSource.ORDINARY_RULE_REFERENCE,
    }),
    QualityMetricId.FACTUAL_SUPPORT_RATE: frozenset({QualityMetricSource.CLAIM_JUDGE}),
    QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY: frozenset({QualityMetricSource.LABELED_EVALUATION}),
    QualityMetricId.CLAIM_CHECK_PROGRESS: frozenset({QualityMetricSource.CLAIM_JUDGE}),
}


class QualityContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, allow_inf_nan=False)


class MetricThresholdV1(QualityContract):
    comparator: ThresholdComparator
    value: float = Field(ge=0.0, le=1.0)


QUALITY_THRESHOLDS = {
    QualityMetricId.CORE_KNOWLEDGE_COVERAGE: MetricThresholdV1(
        comparator=ThresholdComparator.GTE, value=0.90,
    ),
    QualityMetricId.HALLUCINATION_RATE: MetricThresholdV1(
        comparator=ThresholdComparator.LT, value=0.05,
    ),
    QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY: MetricThresholdV1(
        comparator=ThresholdComparator.GTE, value=0.85,
    ),
}


def assess_value(metric_id: QualityMetricId, value: float | None) -> QualityAssessment:
    """Assess a measured value against the fixed registry; never re-derives it."""
    threshold = QUALITY_THRESHOLDS.get(metric_id)
    if value is None:
        return QualityAssessment.NOT_ASSESSED
    if threshold is None:
        return QualityAssessment.NOT_APPLICABLE
    if threshold.comparator is ThresholdComparator.LT:
        # Strict: a real rate of exactly 5% does not satisfy "<5%".
        return QualityAssessment.MET if value < threshold.value else QualityAssessment.NOT_MET
    return QualityAssessment.MET if value >= threshold.value else QualityAssessment.NOT_MET


class RateMetricV1(QualityContract):
    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    metric_id: QualityMetricId
    definition_version: str = Field(min_length=1, max_length=64)
    value: float | None = Field(default=None, ge=0.0, le=1.0)
    status: QualityMetricStatus
    source: QualityMetricSource
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=0)
    assessment: QualityAssessment
    threshold: MetricThresholdV1 | None = None
    evidence_mode: QualityEvidenceMode
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def validate_metric(self) -> "RateMetricV1":
        if any(not _REASON_CODE.match(code) for code in self.reason_codes):
            raise ValueError("reason codes must be controlled short codes")
        if len(set(self.reason_codes)) != len(self.reason_codes):
            raise ValueError("reason codes must be unique")
        if list(self.reason_codes) != sorted(self.reason_codes):
            raise ValueError("reason codes must be stably sorted")
        if self.numerator is not None and self.denominator is not None:
            if self.numerator > self.denominator:
                raise ValueError("numerator cannot exceed denominator")
        allowed = _METRIC_SOURCES[self.metric_id]
        if self.status in {QualityMetricStatus.COMPLETE, QualityMetricStatus.REFERENCE}:
            if self.source not in allowed:
                raise ValueError(f"{self.metric_id.value} cannot use source {self.source.value}")
        elif self.source not in allowed and self.source is not QualityMetricSource.NONE:
            raise ValueError(f"{self.metric_id.value} cannot use source {self.source.value}")
        if self.status is QualityMetricStatus.REFERENCE:
            self._validate_reference()
        elif self.status is QualityMetricStatus.COMPLETE:
            self._validate_complete()
        else:
            if self.value is not None or self.numerator is not None or self.denominator is not None:
                raise ValueError("non-measured status cannot carry a value or counts")
            expected = (QualityAssessment.NOT_APPLICABLE
                        if self.status is QualityMetricStatus.NOT_APPLICABLE
                        else QualityAssessment.NOT_ASSESSED)
            if self.assessment is not expected:
                raise ValueError("non-measured status has a fixed assessment")
        if self.threshold is not None:
            registered = QUALITY_THRESHOLDS.get(self.metric_id)
            if registered is None or self.threshold != registered:
                raise ValueError("threshold must equal the backend registry")
        return self

    def _validate_reference(self) -> None:
        if self.metric_id is not QualityMetricId.HALLUCINATION_RATE:
            raise ValueError("only the hallucination rate has a rule reference")
        if self.definition_version != ORDINARY_REFERENCE_DEFINITION_VERSION:
            raise ValueError("reference requires the fixed rule definition version")
        if self.source is not QualityMetricSource.ORDINARY_RULE_REFERENCE:
            raise ValueError("reference requires the rule-reference source")
        if self.value != ORDINARY_REFERENCE_VALUE:
            raise ValueError("reference value is fixed at 0.05")
        if self.numerator is not None or self.denominator is not None:
            raise ValueError("reference must not fabricate counts")
        if self.assessment is not QualityAssessment.NOT_ASSESSED:
            raise ValueError("reference is never assessed")
        if self.evidence_mode is not QualityEvidenceMode.RULE_REFERENCE:
            raise ValueError("reference requires the rule-reference evidence mode")
        if self.threshold is not None:
            raise ValueError("reference must not carry a pass/fail threshold")

    def _validate_complete(self) -> None:
        if self.definition_version != DEFINITION_VERSIONS[self.metric_id]:
            raise ValueError("complete measurement requires the metric definition version")
        if self.numerator is None or self.denominator is None:
            raise ValueError("complete measurement requires real counts")
        if self.denominator <= 0:
            raise ValueError("complete measurement requires a positive denominator")
        if self.value is None:
            raise ValueError("complete measurement requires a value")
        if abs(self.value - self.numerator / self.denominator) > 1e-12:
            raise ValueError("value must equal numerator / denominator")
        expected = assess_value(self.metric_id, self.value)
        if self.assessment is not expected:
            # A verified-subset rate describes only the measured subset; it must
            # never be assessed as if it covered every resource.
            if not (self.assessment is QualityAssessment.NOT_ASSESSED
                    and "VERIFIED_SUBSET_ONLY" in self.reason_codes):
                raise ValueError("assessment must follow the backend threshold registry")
        if self.threshold is not None and self.metric_id not in QUALITY_THRESHOLDS:
            raise ValueError("metric has no registered threshold")
        if self.metric_id in QUALITY_THRESHOLDS and self.threshold is None:
            raise ValueError("metric requires its registered threshold")


class EvaluationQualityManifestV2(QualityContract):
    """Frozen selection; its hash binds every case to the same experiment."""

    schema_version: Literal["2.0"] = "2.0"
    evaluation_id: str = Field(min_length=1)
    experiment_name: str = Field(min_length=1)
    suite_id: str = Field(min_length=1)
    suite_version: str = Field(min_length=1)
    fixture_version: str = Field(min_length=1)
    coverage_fixture_version: str = Field(min_length=1)
    metric_definition_version: Literal["resource-quality/v2"] = METRIC_POLICY_VERSION
    evidence_mode: Literal["offline_gold", "live_model"]
    source_snapshot_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    suite_data_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    selected_case_targets: dict[str, tuple[str, ...]]

    @model_validator(mode="after")
    def selection(self) -> "EvaluationQualityManifestV2":
        if not self.selected_case_targets or any(
            not key or not targets or len(targets) != len(set(targets))
            or any(not target for target in targets)
            for key, targets in self.selected_case_targets.items()
        ):
            raise ValueError("manifest requires nonempty, unique frozen targets per case")
        return self


class EvaluationQualityCaseV2(QualityContract):
    schema_version: Literal["2.0"] = "2.0"
    manifest_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    case_id: str = Field(min_length=1)
    generation_status: Literal["completed", "failed", "reference_only"]
    expected_difficulty: str = Field(min_length=1, max_length=32)
    predicted_difficulty: str | None = Field(default=None, min_length=1, max_length=32)
    run_id: str | None = None
    resource_id: str | None = None
    resource_version: int | None = Field(default=None, ge=1)
    review_id: str | None = None
    ordinary_coverage: "OrdinaryCoverageCaseV1"
    claim_status: QualityMetricStatus = QualityMetricStatus.UNAVAILABLE
    claim_counts: "ClaimMetricCountsV1 | None" = None
    failure_code: str | None = None

    @model_validator(mode="after")
    def identity(self) -> "EvaluationQualityCaseV2":
        if self.ordinary_coverage.case_id != self.case_id:
            raise ValueError("coverage case identity mismatch")
        if self.claim_status == QualityMetricStatus.COMPLETE and self.claim_counts is None:
            raise ValueError("complete Claim evaluation requires exhaustive counts")
        if self.claim_status == QualityMetricStatus.COMPLETE and self.claim_counts.incomplete_claim_total:
            raise ValueError("complete Claim evaluation cannot contain incomplete facts")
        if self.claim_status != QualityMetricStatus.COMPLETE and self.claim_counts is not None:
            raise ValueError("unmeasured Claim result cannot expose partial counts")
        return self


class EvaluationResourceQualityV2(QualityContract):
    manifest: EvaluationQualityManifestV2
    manifest_hash: str
    status: Literal["complete", "incomplete", "invalid"]
    planned_case_total: int = Field(ge=0)
    received_case_total: int = Field(ge=0)
    failed_case_total: int = Field(ge=0)
    coverage_known_target_total: int = Field(ge=0)
    covered_target_total: int = Field(ge=0)
    expected_target_total: int = Field(ge=0)
    coverage_unknown_case_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()
    coverage: RateMetricV1
    hallucination: RateMetricV1
    difficulty: RateMetricV1


class CoverageTargetV1(QualityContract):
    """One frozen target result.  Only safe locators are projected."""

    target_id: str = Field(min_length=1, max_length=256)
    display_name: str | None = Field(default=None, max_length=256)
    status: Literal["covered", "missing"]
    paragraph_id: str | None = Field(default=None, max_length=128)
    heading_path: tuple[str, ...] = ()
    unit_id: str | None = Field(default=None, max_length=128)
    reason_code: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def safe_locator(self) -> "CoverageTargetV1":
        if self.status == "covered" and not (
            self.paragraph_id or self.heading_path or self.unit_id
        ):
            raise ValueError("covered target requires a safe location")
        if self.status == "missing" and (self.paragraph_id or self.heading_path or self.unit_id):
            raise ValueError("missing target cannot cite a location")
        if self.reason_code is not None and not _REASON_CODE.match(self.reason_code):
            raise ValueError("invalid target reason code")
        return self


class SeverityCountsV1(QualityContract):
    low: int = Field(default=0, ge=0)
    medium: int = Field(default=0, ge=0)
    high: int = Field(default=0, ge=0)
    critical: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return self.low + self.medium + self.high + self.critical


class DimensionCountsV1(QualityContract):
    factual_evidence: int = Field(default=0, ge=0)
    coverage: int = Field(default=0, ge=0)
    difficulty: int = Field(default=0, ge=0)
    self_contained: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return (
            self.factual_evidence + self.coverage + self.difficulty + self.self_contained
        )


class IssueStatisticsV1(QualityContract):
    """Numeric projection of the private ledger; never the ledger itself."""

    history_completeness: Literal["complete", "partial", "unavailable"] = "unavailable"
    open_issue_total: int | None = Field(default=None, ge=0)
    open_by_severity: SeverityCountsV1 | None = None
    open_by_dimension: DimensionCountsV1 | None = None
    fixed_issue_total: int | None = Field(default=None, ge=0)
    false_positive_issue_total: int | None = Field(default=None, ge=0)
    still_open_issue_total: int | None = Field(default=None, ge=0)
    unverifiable_issue_total: int | None = Field(default=None, ge=0)
    reopened_issue_total: int | None = Field(default=None, ge=0)
    blocked_by_issue_total: int = Field(default=0, ge=0)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "IssueStatisticsV1":
        if self.history_completeness == "unavailable":
            if any(value is not None for value in (
                self.open_issue_total, self.fixed_issue_total,
                self.false_positive_issue_total, self.still_open_issue_total,
                self.unverifiable_issue_total, self.reopened_issue_total,
            )):
                raise ValueError("unavailable history cannot carry counters")
            if self.open_by_severity is not None or self.open_by_dimension is not None:
                raise ValueError("unavailable history cannot carry distributions")
            return self
        if self.open_issue_total is None:
            raise ValueError("available history requires the open issue count")
        if self.open_by_severity is not None and self.open_by_severity.total != self.open_issue_total:
            raise ValueError("severity distribution must match the open total")
        if self.open_by_dimension is not None and self.open_by_dimension.total != self.open_issue_total:
            raise ValueError("dimension distribution must match the open total")
        return self


class OrdinaryReviewQualityV1(QualityContract):
    """Discrete ordinary-review facts; coverage is the only ratio metric."""

    status: Literal[
        "complete", "failed", "incomplete", "not_requested", "unavailable", "legacy_unavailable"
    ]
    contract_version: str | None = Field(default=None, max_length=32)
    review_id: str | None = Field(default=None, max_length=128)
    review_step_id: str | None = Field(default=None, max_length=128)
    review_step_sequence: int | None = Field(default=None, ge=0)
    decision: Literal["approve", "revise", "reject", "human_review"] | None = None
    factual_evidence: Literal["pass", "fail", "insufficient", "not_evaluated"] = "not_evaluated"
    difficulty: Literal["pass", "fail", "insufficient", "not_evaluated"] = "not_evaluated"
    self_contained: Literal["pass", "fail", "insufficient", "not_evaluated"] = "not_evaluated"
    target_total: int | None = Field(default=None, ge=0)
    covered_target_total: int | None = Field(default=None, ge=0)
    missing_target_total: int | None = Field(default=None, ge=0)
    truncated_issue_count: bool = False
    failure_code: str | None = Field(default=None, max_length=64)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "OrdinaryReviewQualityV1":
        counts = (self.target_total, self.covered_target_total, self.missing_target_total)
        if any(value is not None for value in counts):
            if any(value is None for value in counts):
                raise ValueError("target counts are all-or-nothing")
            if self.covered_target_total + self.missing_target_total != self.target_total:
                raise ValueError("target counts must add up")
            if self.target_total <= 0:
                raise ValueError("a measured target set cannot be empty")
        elif self.status == "complete":
            raise ValueError("a complete ordinary review requires target counts")
        return self


class ClaimMetricCountsV1(QualityContract):
    claim_total: int = Field(default=0, ge=0)
    factual_claim_total: int = Field(default=0, ge=0)
    supported_claim_total: int = Field(default=0, ge=0)
    contradicted_claim_total: int = Field(default=0, ge=0)
    not_in_evidence_claim_total: int = Field(default=0, ge=0)
    non_factual_claim_total: int = Field(default=0, ge=0)
    incomplete_claim_total: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def coherent(self) -> "ClaimMetricCountsV1":
        if self.incomplete_claim_total > self.factual_claim_total:
            raise ValueError("incomplete cannot exceed factual")
        accounted = (
            self.supported_claim_total + self.contradicted_claim_total
            + self.not_in_evidence_claim_total + self.incomplete_claim_total
        )
        if accounted != self.factual_claim_total:
            raise ValueError("factual verdict counts must be exhaustive")
        if self.claim_total < self.factual_claim_total:
            raise ValueError("claim total cannot be below the factual total")
        return self


class ClaimQualityV1(QualityContract):
    requested: bool
    status: Literal[
        "complete", "reference", "pending", "incomplete", "failed", "not_applicable",
        "not_requested", "unavailable", "legacy_unavailable",
    ]
    review_id: str | None = Field(default=None, max_length=128)
    counts: ClaimMetricCountsV1 | None = None
    hallucination: RateMetricV1
    support_rate: RateMetricV1 | None = None
    progress: RateMetricV1
    failure_code: str | None = Field(default=None, max_length=64)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "ClaimQualityV1":
        if self.status == "complete":
            if self.counts is None:
                raise ValueError("a complete Claim audit requires its counts")
        elif self.status == "not_requested" and self.requested:
            raise ValueError("requested Claim audit cannot be not_requested")
        return self


class DifficultyFitV1(QualityContract):
    """Single-resource difficulty state; never a percentage accuracy."""

    dimension_status: Literal["pass", "fail", "insufficient", "not_evaluated"] = "not_evaluated"
    estimated_difficulty: str | None = Field(default=None, max_length=16)
    match_status: Literal["matched", "too_easy", "challenging", "too_hard", "not_measured"] = "not_measured"
    scale_version: Literal["declared-band/v1"] = "declared-band/v1"
    reason_codes: tuple[str, ...] = ()


class SourceBindingQualityV1(QualityContract):
    status: Literal["complete", "partial", "not_measured", "failed"] = "not_measured"
    source_ref_total: int = Field(default=0, ge=0)
    verified_ref_total: int = Field(default=0, ge=0)
    unique_document_total: int = Field(default=0, ge=0)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "SourceBindingQualityV1":
        if self.verified_ref_total > self.source_ref_total:
            raise ValueError("verified references cannot exceed the total")
        return self


class ResourceQualityMetricsV1(QualityContract):
    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    metric_policy_version: Literal["resource-quality/v2"] = METRIC_POLICY_VERSION
    run_id: str = Field(min_length=1)
    resource_spec_id: str | None = Field(default=None, max_length=64)
    resource_id: str = Field(min_length=1)
    resource_version: int = Field(ge=1)
    resource_type: str = Field(min_length=1, max_length=32)
    topic: str = ""
    display_order: int = Field(default=0, ge=0)
    published: bool = False
    review_id: str | None = Field(default=None, max_length=128)
    coverage: RateMetricV1
    hallucination: RateMetricV1
    factual_support: RateMetricV1 | None = None
    claim: ClaimQualityV1
    ordinary_review: OrdinaryReviewQualityV1
    difficulty_fit: DifficultyFitV1
    issue_statistics: IssueStatisticsV1
    source_binding: SourceBindingQualityV1
    target_coverage: tuple[CoverageTargetV1, ...] = ()
    availability: QualityAvailability = QualityAvailability.AVAILABLE
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "ResourceQualityMetricsV1":
        if self.coverage.metric_id is not QualityMetricId.CORE_KNOWLEDGE_COVERAGE:
            raise ValueError("coverage must be the core knowledge coverage metric")
        if self.hallucination.metric_id is not QualityMetricId.HALLUCINATION_RATE:
            raise ValueError("hallucination must be the hallucination metric")
        if self.claim.hallucination != self.hallucination:
            raise ValueError("claim projection must carry the same hallucination metric")
        targets = self.target_coverage
        if targets:
            ids = [item.target_id for item in targets]
            if len(set(ids)) != len(ids):
                raise ValueError("duplicate target results")
            covered = sum(item.status == "covered" for item in targets)
            if self.ordinary_review.covered_target_total is not None:
                if self.ordinary_review.covered_target_total != covered:
                    raise ValueError("coverage count must match the target list")
                if self.ordinary_review.target_total != len(targets):
                    raise ValueError("target total must match the target list")
            if self.ordinary_review.review_id != self.review_id:
                raise ValueError("ordinary review binding must match the resource review")
        return self


class CoverageStatusBucketsV1(QualityContract):
    """Coverage result completeness per resource; buckets partition the total."""

    complete: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    incomplete: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    not_requested: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)
    unavailable: int = Field(default=0, ge=0)
    legacy_unavailable: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return (
            self.complete + self.pending + self.incomplete + self.failed
            + self.not_requested + self.not_applicable + self.unavailable
            + self.legacy_unavailable
        )


class ClaimStatusBucketsV1(QualityContract):
    """Claim measurement state per resource; reference is kept out of complete."""

    complete: int = Field(default=0, ge=0)
    reference: int = Field(default=0, ge=0)
    pending: int = Field(default=0, ge=0)
    incomplete: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    not_requested: int = Field(default=0, ge=0)
    not_applicable: int = Field(default=0, ge=0)
    unavailable: int = Field(default=0, ge=0)
    legacy_unavailable: int = Field(default=0, ge=0)

    @property
    def total(self) -> int:
        return (
            self.complete + self.reference + self.pending + self.incomplete
            + self.failed + self.not_requested + self.not_applicable
            + self.unavailable + self.legacy_unavailable
        )


class ResourceQualitySummaryV1(QualityContract):
    """Resource-target aggregation, not a course-wide node coverage rate."""

    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    metric_policy_version: Literal["resource-quality/v2"] = METRIC_POLICY_VERSION
    resource_total: int = Field(ge=0)
    coverage: RateMetricV1
    coverage_buckets: CoverageStatusBucketsV1 = Field(default_factory=CoverageStatusBucketsV1)
    coverage_target_total: int | None = Field(default=None, ge=0)
    coverage_covered_target_total: int | None = Field(default=None, ge=0)
    coverage_missing_target_total: int | None = Field(default=None, ge=0)
    coverage_unknown_resource_total: int = Field(default=0, ge=0)
    claim_buckets: ClaimStatusBucketsV1 = Field(default_factory=ClaimStatusBucketsV1)
    claim_verified_resource_total: int = Field(default=0, ge=0)
    claim_risk_fact_total: int = Field(default=0, ge=0)
    claim_factual_total: int = Field(default=0, ge=0)
    claim_unverified_subset_rate: RateMetricV1 | None = None
    reference_resource_total: int = Field(default=0, ge=0)
    reference_value: float | None = Field(default=None, ge=0.0, le=1.0)
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "ResourceQualitySummaryV1":
        if self.coverage_buckets.total != self.resource_total:
            raise ValueError("coverage buckets must partition the resource total")
        if self.claim_buckets.total != self.resource_total:
            raise ValueError("claim buckets must partition the resource total")
        if self.coverage_buckets.complete + self.coverage_buckets.unavailable > self.resource_total:
            raise ValueError("impossible coverage buckets")
        if self.reference_resource_total != self.claim_buckets.reference:
            raise ValueError("reference total must match the claim reference bucket")
        if self.reference_resource_total == 0 and self.reference_value is not None:
            raise ValueError("a reference value requires reference resources")
        if self.coverage.status is QualityMetricStatus.COMPLETE:
            if self.coverage_target_total is None or self.coverage_covered_target_total is None:
                raise ValueError("complete aggregation requires target counts")
            if self.coverage.denominator != self.coverage_target_total:
                raise ValueError("aggregation denominator must be the target total")
            if self.coverage.numerator != self.coverage_covered_target_total:
                raise ValueError("aggregation numerator must be the covered target total")
        return self


class RunResourceQualityResponseV1(QualityContract):
    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    run_id: str = Field(min_length=1)
    source_revision: str = Field(pattern=r"^rq_[0-9a-f]{64}$")
    availability: QualityAvailability
    metric_policy_version: Literal["resource-quality/v2"] = METRIC_POLICY_VERSION
    items: tuple[ResourceQualityMetricsV1, ...] = ()
    summary: ResourceQualitySummaryV1
    reason_codes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "RunResourceQualityResponseV1":
        if self.summary.resource_total != len(self.items):
            raise ValueError("summary resource total must match the item list")
        keys = [(item.display_order, item.resource_version, item.resource_id) for item in self.items]
        if keys != sorted(keys):
            raise ValueError("items must use the deterministic order")
        if len({item.resource_id for item in self.items}) != len(self.items):
            raise ValueError("duplicate resource in one run projection")
        return self


class DifficultyLabelResultV1(QualityContract):
    case_id: str = Field(min_length=1)
    expected_label: str = Field(min_length=1, max_length=32)
    predicted_label: str = Field(min_length=1, max_length=32)


class OrdinaryCoverageTargetV1(QualityContract):
    target_id: str = Field(min_length=1, max_length=256)
    covered: bool


class OrdinaryCoverageCaseV1(QualityContract):
    """One evaluation case's per-target ordinary-review result."""

    case_id: str = Field(min_length=1)
    observed: bool = True
    failure_code: str | None = Field(default=None, max_length=64)
    targets: tuple[OrdinaryCoverageTargetV1, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "OrdinaryCoverageCaseV1":
        if not self.observed and self.targets:
            raise ValueError("an unobserved case cannot carry target results")
        if self.observed and not self.targets:
            raise ValueError("an observed case requires its target results")
        ids = [item.target_id for item in self.targets]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate coverage target")
        if self.failure_code is not None and self.observed:
            raise ValueError("an observed case cannot carry a failure code")
        return self


class OrdinaryCoverageEvaluationV1(QualityContract):
    """Competition coverage over ``(case_id, target_id)`` units."""

    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    definition_version: Literal["ordinary-target-coverage/v2"] = COVERAGE_DEFINITION_VERSION
    coverage_fixture_version: str = Field(min_length=1)
    evidence_mode: QualityEvidenceMode
    planned_case_total: int = Field(ge=0)
    observed_case_total: int = Field(ge=0)
    failed_case_total: int = Field(ge=0)
    missing_case_count: int = Field(ge=0)
    planned_unit_total: int = Field(ge=0)
    covered_unit_total: int = Field(ge=0)
    missing_unit_total: int | None = Field(default=None, ge=0)
    unknown_case_ids: tuple[str, ...] = ()
    metric: RateMetricV1
    cases: tuple[OrdinaryCoverageCaseV1, ...] = ()

    @model_validator(mode="after")
    def coherent(self) -> "OrdinaryCoverageEvaluationV1":
        if self.metric.metric_id is not QualityMetricId.CORE_KNOWLEDGE_COVERAGE:
            raise ValueError("coverage evaluation must use the coverage metric")
        if self.observed_case_total + self.missing_case_count != self.planned_case_total:
            raise ValueError("case buckets must partition the planned cases")
        if self.covered_unit_total > self.planned_unit_total:
            raise ValueError("covered units cannot exceed planned units")
        if self.missing_unit_total is not None:
            if self.covered_unit_total + self.missing_unit_total != self.planned_unit_total:
                raise ValueError("unit buckets must partition the planned units")
        return self


class DifficultyAdaptationReportV1(QualityContract):
    """Evaluation-only accuracy with its denominator and confusion matrix."""

    schema_version: Literal["1.0"] = QUALITY_SCHEMA_VERSION
    metric: RateMetricV1
    fixture_version: str
    evidence_mode: QualityEvidenceMode
    planned_case_total: int = Field(ge=0)
    correct_case_total: int = Field(ge=0)
    labels: tuple[str, ...] = ()
    confusion_matrix: dict[str, dict[str, int]] = Field(default_factory=dict)


EvaluationQualityCaseV2.model_rebuild()

__all__ = [
    "EvaluationQualityManifestV2",
    "EvaluationQualityCaseV2",
    "EvaluationResourceQualityV2",
    "CLAIM_RISK_DEFINITION_VERSION",
    "COVERAGE_DEFINITION_VERSION",
    "CoverageStatusBucketsV1",
    "CoverageTargetV1",
    "ClaimMetricCountsV1",
    "ClaimQualityV1",
    "ClaimStatusBucketsV1",
    "DifficultyAdaptationReportV1",
    "DifficultyFitV1",
    "DifficultyLabelResultV1",
    "DIFFICULTY_ACCURACY_DEFINITION_VERSION",
    "IssueStatisticsV1",
    "METRIC_POLICY_VERSION",
    "MetricThresholdV1",
    "ORDINARY_REFERENCE_DEFINITION_VERSION",
    "ORDINARY_REFERENCE_VALUE",
    "OrdinaryCoverageCaseV1",
    "OrdinaryCoverageEvaluationV1",
    "OrdinaryCoverageTargetV1",
    "OrdinaryReviewQualityV1",
    "QUALITY_THRESHOLDS",
    "QualityAssessment",
    "QualityAvailability",
    "QualityEvidenceMode",
    "QualityMetricId",
    "QualityMetricSource",
    "QualityMetricStatus",
    "RateMetricV1",
    "ResourceQualityMetricsV1",
    "ResourceQualitySummaryV1",
    "RunResourceQualityResponseV1",
    "SourceBindingQualityV1",
    "ThresholdComparator",
    "assess_value",
]
