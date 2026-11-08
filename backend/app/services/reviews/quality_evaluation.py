"""Validate frozen evaluation records and calculate independent quality metrics."""
from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from app.models.reviews.claims import ClaimMetricSummary, ClaimMetricStatus

from app.models.reviews.quality_metrics import (
    DIFFICULTY_ACCURACY_DEFINITION_VERSION,
    QUALITY_THRESHOLDS, DifficultyLabelResultV1, EvaluationQualityCaseV2,
    EvaluationQualityManifestV2, EvaluationResourceQualityV2, QualityAssessment,
    QualityEvidenceMode, QualityMetricId, QualityMetricSource, QualityMetricStatus,
    RateMetricV1,
)
from app.services.reviews.quality_metrics import (
    claim_hallucination_metric, difficulty_adaptation_report, ordinary_coverage_evaluation,
)


def manifest_hash(manifest: EvaluationQualityManifestV2) -> str:
    payload = json.dumps(manifest.model_dump(mode="json"), sort_keys=True,
                         separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def aggregate_evaluation(
    manifest: EvaluationQualityManifestV2, records: Sequence[EvaluationQualityCaseV2],
    *, record_conflict: bool = False,
) -> EvaluationResourceQualityV2:
    identity = manifest_hash(manifest)
    selected = manifest.selected_case_targets
    mode = QualityEvidenceMode(manifest.evidence_mode)
    by_case: dict[str, EvaluationQualityCaseV2] = {}
    invalid = record_conflict
    live_bindings: dict[tuple, str] = {}
    for record in records:
        if record.manifest_hash != identity or record.case_id not in selected:
            invalid = True
            continue
        previous = by_case.get(record.case_id)
        if previous is not None and previous != record:
            invalid = True
        by_case[record.case_id] = record
        if mode is QualityEvidenceMode.LIVE_MODEL:
            if record.generation_status == "reference_only":
                invalid = True
            binding = (record.resource_id, record.resource_version)
            if record.resource_id is not None:
                owner = live_bindings.get(binding)
                if owner is not None and owner != record.case_id:
                    invalid = True
                live_bindings[binding] = record.case_id
        coverage = record.ordinary_coverage
        if coverage.observed and {item.target_id for item in coverage.targets} != set(selected[record.case_id]):
            invalid = True
        if (mode is QualityEvidenceMode.LIVE_MODEL
                and (coverage.observed or record.generation_status == "completed"
                     or record.claim_status is QualityMetricStatus.COMPLETE) and not all((
            record.run_id, record.resource_id, record.resource_version, record.review_id,
        ))):
            invalid = True
    complete = len(by_case) == len(selected) and not invalid
    reasons = ("EVALUATION_RECORD_CONFLICT",) if invalid else (
        ("EVALUATION_CASES_MISSING",) if not complete else ()
    )
    coverage_report = ordinary_coverage_evaluation(
        [record.ordinary_coverage for record in by_case.values()] if not invalid else [],
        planned_case_total=len(selected), planned_unit_total=sum(map(len, selected.values())),
        fixture_version=manifest.coverage_fixture_version, evidence_mode=mode,
    )
    coverage = coverage_report.metric
    labels = [DifficultyLabelResultV1(
        case_id=record.case_id, expected_label=record.expected_difficulty,
        predicted_label=(record.predicted_difficulty or "NOT_GENERATED")
        if record.generation_status != "failed" else "NOT_GENERATED",
    ) for record in by_case.values()]
    difficulty = difficulty_adaptation_report(
        labels if not invalid else [], planned_case_total=len(selected),
        fixture_version=manifest.fixture_version, evidence_mode=mode,
    ).metric
    claim_complete = complete and all(
        record.claim_status in {QualityMetricStatus.COMPLETE, QualityMetricStatus.NOT_APPLICABLE}
        and (mode is QualityEvidenceMode.OFFLINE_GOLD or record.generation_status == "completed")
        for record in by_case.values()
    )
    counts = [record.claim_counts for record in by_case.values() if record.claim_counts is not None]
    summary = ClaimMetricSummary(
        metric_status=ClaimMetricStatus.COMPLETE if claim_complete else ClaimMetricStatus.INCOMPLETE,
        **{name: sum(getattr(count, name) for count in counts)
           for name in ("claim_total", "factual_claim_total", "supported_claim_total",
                        "contradicted_claim_total", "not_in_evidence_claim_total",
                        "non_factual_claim_total", "incomplete_claim_total")},
    )
    hallucination = claim_hallucination_metric(
        summary, requested=True, conflict=invalid, evidence_mode=mode,
    )
    # Conflicting records invalidate every displayed measurement in this group.
    if invalid:
        difficulty = RateMetricV1(
            metric_id=QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY,
            definition_version=DIFFICULTY_ACCURACY_DEFINITION_VERSION,
            status=QualityMetricStatus.UNAVAILABLE, source=QualityMetricSource.NONE,
            assessment=QualityAssessment.NOT_ASSESSED, evidence_mode=mode,
            threshold=QUALITY_THRESHOLDS[QualityMetricId.DIFFICULTY_ADAPTATION_ACCURACY],
            reason_codes=reasons,
        )
    return EvaluationResourceQualityV2(
        manifest=manifest, manifest_hash=identity,
        status="invalid" if invalid else "complete" if complete else "incomplete",
        planned_case_total=len(selected), received_case_total=len(by_case),
        failed_case_total=sum(record.generation_status == "failed" for record in by_case.values()),
        coverage_known_target_total=sum(len(record.ordinary_coverage.targets) for record in by_case.values()
                                        if record.ordinary_coverage.observed) if not invalid else 0,
        covered_target_total=coverage_report.covered_unit_total,
        expected_target_total=sum(map(len, selected.values())),
        coverage_unknown_case_ids=tuple(sorted(set(selected) - {
            record.case_id for record in by_case.values() if record.ordinary_coverage.observed
        })) if not invalid else tuple(sorted(selected)),
        reason_codes=reasons, coverage=coverage, hallucination=hallucination, difficulty=difficulty,
    )
