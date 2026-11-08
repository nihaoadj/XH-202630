"""Read-only projection of resource quality metrics for one Run (T48).

The service never computes a second version of a metric: it turns already-read
facts into the pure contracts in ``services.reviews.quality_metrics``.  Private
ledger content (answers, rubrics, prompts, evidence excerpts, model rationale)
is reduced to counts, verdict states and safe locators before it leaves this
module.

Version binding is strict.  A metric is only reported when the ledger,
resource version, spec targets and Claim rows all describe the same
``(run, resource_spec_id, resource_id, version, review_id)`` identity; a
mismatch degrades to an explicit unavailable state instead of borrowing a
neighbouring version.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

from app.db.audit.base import StepReviewAudit
from app.db.audit.quality_read import (
    UNSUPPORTED,
    QualitySourceBundle,
    read_quality_sources,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.reviews.claims import (
    ClaimJudgement,
    ClaimJudgementStatus,
    ClaimMetricStatus,
    ClaimRecord,
    compute_claim_metric,
)
from app.models.reviews.claim_resolution import (
    ClaimResolutionConflict,
    resolve_effective_claim_judgements,
)
from app.models.reviews.quality_metrics import (
    COVERAGE_DEFINITION_VERSION,
    ClaimQualityV1,
    CoverageTargetV1,
    DimensionCountsV1,
    DifficultyFitV1,
    IssueStatisticsV1,
    OrdinaryReviewQualityV1,
    QualityAvailability,
    QualityEvidenceMode,
    QualityMetricStatus,
    ResourceQualityMetricsV1,
    ResourceQualitySummaryV1,
    RunResourceQualityResponseV1,
    SeverityCountsV1,
    SourceBindingQualityV1,
)
from app.models.shared.workflow import normalize_review_status, review_status_is_approved
from app.services.reviews.quality_metrics import (
    aggregate_quality_summary,
    availability_for,
    claim_quality,
    measured_coverage,
    ordinary_reference_metric,
    unmeasured_coverage,
)


METRIC_POLICY_VERSION = "resource-quality/v2"

# A Claim audit that was requested but never produced rows, with no durable
# skip marker, is unknown rather than "zero risk".
CLAIM_STATUS_COMPLETE = "complete"

_SAFE_DIMENSIONS = ("factual_evidence", "coverage", "difficulty", "self_contained")


class ResourceQualityNotFound(LookupError):
    """The requested resource id is not part of this run's persisted output."""


@dataclass(frozen=True)
class _ReviewEvidence:
    audit: Any | None
    resource_audit: Any | None
    entry: StepReviewAudit | None
    failure_code: str | None


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _revision(items: Sequence[ResourceQualityMetricsV1], run_id: str) -> str:
    payload = {
        "run_id": run_id,
        "metric_policy_version": METRIC_POLICY_VERSION,
        "coverage_definition": COVERAGE_DEFINITION_VERSION,
        "items": [item.model_dump(mode="json") for item in items],
    }
    digest = hashlib.sha256(_stable_json(payload).encode("utf-8")).hexdigest()
    return f"rq_{digest}"


def _safe_location(location) -> dict[str, Any]:
    """Project only server-indexed locators; never quotes or free text."""
    if location is None:
        return {}
    paragraph = getattr(location, "paragraph_id", None)
    heading = tuple(getattr(location, "heading_path", ()) or ())
    unit = getattr(location, "unit_id", None)
    return {
        "paragraph_id": paragraph if isinstance(paragraph, str) else None,
        "heading_path": tuple(value for value in heading if isinstance(value, str)),
        "unit_id": unit if isinstance(unit, str) else None,
    }


def _targets_from_output(output) -> tuple[CoverageTargetV1, ...]:
    targets = []
    for item in getattr(output, "targets", ()) or ():
        target_id = getattr(item, "target", None)
        if not isinstance(target_id, str) or not target_id:
            continue
        location = _safe_location(getattr(item, "location", None))
        targets.append(CoverageTargetV1(
            target_id=target_id,
            display_name=target_id,
            status="covered" if getattr(item, "status", "") == "covered" else "missing",
            paragraph_id=location.get("paragraph_id"),
            heading_path=location.get("heading_path", ()),
            unit_id=location.get("unit_id"),
            reason_code=None,
        ))
    return tuple(targets)


def _dimension(output, name: str) -> str:
    dimensions = getattr(output, "dimensions", None)
    value = getattr(dimensions, name, None) if dimensions is not None else None
    return value if value in {"pass", "fail", "insufficient"} else "not_evaluated"


def _issue_statistics(ledger, *, truncated: bool) -> IssueStatisticsV1:
    histories = list(getattr(ledger, "issues", ()) or ())
    if ledger is None:
        return IssueStatisticsV1(history_completeness="unavailable")
    severities = SeverityCountsV1()
    dimensions = DimensionCountsV1()
    open_total = 0
    blocked = 0
    for history in histories:
        if getattr(history, "status", "open") != "open":
            continue
        issue = history.issue
        open_total += 1
        blocked += bool(getattr(issue, "blocking", False))
        severity = getattr(issue, "severity", "")
        if severity in {"low", "medium", "high", "critical"}:
            severities = severities.model_copy(update={severity: getattr(severities, severity) + 1})
        dimension = getattr(issue, "dimension", "")
        if dimension in _SAFE_DIMENSIONS:
            dimensions = dimensions.model_copy(update={dimension: getattr(dimensions, dimension) + 1})

    latest: dict[str, str] = {}
    reopened: set[str] = set()
    for observation in getattr(ledger, "observations", ()) or ():
        output = getattr(observation, "output", None)
        if output is None:
            continue
        for resolution in getattr(output, "resolutions", ()) or ():
            issue_id = getattr(resolution, "issue_id", None)
            result = getattr(resolution, "result", None)
            if isinstance(issue_id, str) and result in {"fixed", "still_open", "false_positive", "unverifiable"}:
                latest[issue_id] = result
        for item in getattr(output, "reopen", ()) or ():
            issue_id = getattr(item, "issue_id", None)
            if isinstance(issue_id, str):
                reopened.add(issue_id)
                latest.pop(issue_id, None)
        for resolution in getattr(output, "resolutions", ()) or ():
            if getattr(resolution, "result", None) == "fixed":
                reopened.discard(resolution.issue_id)
    counts = {
        "fixed": sum(value == "fixed" for value in latest.values()),
        "false_positive": sum(value == "false_positive" for value in latest.values()),
        "still_open": sum(value == "still_open" for value in latest.values()),
        "unverifiable": sum(value == "unverifiable" for value in latest.values()),
    }
    # A reopened issue is not "currently fixed" just because an older round
    # resolved it; keep it out of the fixed total and count it separately.
    fixed = sum(
        1 for issue_id, value in latest.items()
        if value == "fixed" and issue_id not in reopened
    )
    return IssueStatisticsV1(
        history_completeness="partial" if truncated else "complete",
        open_issue_total=open_total,
        open_by_severity=severities,
        open_by_dimension=dimensions,
        fixed_issue_total=fixed,
        false_positive_issue_total=counts["false_positive"],
        still_open_issue_total=counts["still_open"],
        unverifiable_issue_total=counts["unverifiable"],
        reopened_issue_total=len(reopened),
        blocked_by_issue_total=blocked,
    )


def _ledger_truncated(output, ledger) -> bool:
    if getattr(output, "omitted_blocking_issues", False):
        return True
    issues = getattr(output, "issues", ()) or ()
    return len(issues) >= 300


class ResourceQualityQueryService:
    """Read-only quality projection; no model call and no workflow replay."""

    def __init__(
        self,
        *,
        audit_repository,
        resource_repository,
        claim_repository=None,
        generation_job_repository=None,
        supplement_repository=None,
    ):
        self.audit_repository = audit_repository
        self.resource_repository = resource_repository
        self.claim_repository = claim_repository
        self.generation_job_repository = generation_job_repository
        self.supplement_repository = supplement_repository

    # -- public API ------------------------------------------------------
    def get_run_quality(self, run_id: str, *, resource_id: str | None = None) -> RunResourceQualityResponseV1:
        bundle = self._load(run_id)
        items = self.build_items(bundle)
        if resource_id is not None:
            selected = [item for item in items if item.resource_id == resource_id]
            if not selected:
                raise ResourceQualityNotFound(resource_id)
            items = selected
        items = tuple(items)
        return RunResourceQualityResponseV1(
            run_id=run_id,
            source_revision=_revision(items, run_id),
            availability=(
                QualityAvailability.UNAVAILABLE if bundle.read_mode == UNSUPPORTED
                else availability_for(items)
            ),
            items=items,
            summary=aggregate_quality_summary(items),
            reason_codes=tuple(
                sorted({bundle.failure_code} if bundle.failure_code else set())
            ),
        )

    def items_for_runs(self, run_ids: Sequence[str]) -> tuple[ResourceQualityMetricsV1, ...]:
        """Report-facing reuse of the same projection for visible resources."""
        seen: dict[str, ResourceQualityMetricsV1] = {}
        for run_id in dict.fromkeys(run_ids):
            for item in self.build_items(self._load(run_id)):
                seen[item.resource_id] = item
        return tuple(seen.values())

    def unavailable_item(self, resource: LearningResource) -> ResourceQualityMetricsV1:
        """Keep a visible resource in the denominator when its sources are missing."""
        return self._build_item(
            QualitySourceBundle(run_id=resource.run_id or "unknown", read_mode=UNSUPPORTED),
            resource, None, claim_requested=None,
        )

    def summarize_items(
        self, items: Sequence[ResourceQualityMetricsV1],
    ) -> ResourceQualitySummaryV1:
        return aggregate_quality_summary(items)

    # -- reading ---------------------------------------------------------
    def _load(self, run_id: str) -> QualitySourceBundle:
        return read_quality_sources(
            run_id,
            audit_repository=self.audit_repository,
            resource_repository=self.resource_repository,
            claim_repository=self.claim_repository,
            generation_job_repository=self.generation_job_repository,
            supplement_repository=self.supplement_repository,
        )

    # -- assembly --------------------------------------------------------
    def build_items(self, bundle: QualitySourceBundle) -> list[ResourceQualityMetricsV1]:
        if not bundle.resources:
            return []
        specs = {spec.resource_spec_id: spec for spec in bundle.specs}
        claim_requested = self._claim_requested(bundle)
        items: list[ResourceQualityMetricsV1] = []
        for resource in sorted(bundle.resources, key=self._sort_key(specs)):
            spec = self._spec_for(resource, specs)
            items.append(self._build_item(
                bundle, resource, spec, claim_requested=claim_requested,
            ))
        return items

    @staticmethod
    def _sort_key(specs):
        def key(resource: LearningResource):
            spec = ResourceQualityQueryService._spec_for(resource, specs)
            return (
                spec.display_order if spec is not None else 0,
                resource.version,
                resource.resource_id,
            )
        return key

    @staticmethod
    def _spec_for(resource: LearningResource, specs):
        spec = specs.get(resource.resource_spec_id or "")
        if (spec is not None and spec.run_id == resource.run_id
                and spec.resource_family_id == resource.resource_family_id
                and spec.resource_type == resource.resource_type):
            return spec
        return None

    def _claim_requested(self, bundle: QualitySourceBundle) -> bool | None:
        projection = bundle.checkpoints[-1].state_projection if bundle.checkpoints else {}
        if isinstance(projection.get("include_claim_check"), bool):
            return projection["include_claim_check"]
        for payload in (bundle.request_snapshot, bundle.job_request_payload):
            if isinstance(payload, dict) and isinstance(payload.get("include_claim_check"), bool):
                return payload["include_claim_check"]
        return None

    @staticmethod
    def _review_enabled(bundle: QualitySourceBundle) -> bool | None:
        for payload in (bundle.request_snapshot, bundle.job_request_payload):
            if isinstance(payload, dict) and isinstance(payload.get("include_review"), bool):
                return payload["include_review"]
        return None

    def _build_item(
        self,
        bundle: QualitySourceBundle,
        resource: LearningResource,
        spec,
        *,
        claim_requested: bool | None,
    ) -> ResourceQualityMetricsV1:
        evidence = self._review_evidence(bundle, resource)
        ledger, ledger_kind = self._exact_ledger(evidence, resource)
        frozen_targets = self._frozen_targets(spec)
        targets: tuple[CoverageTargetV1, ...] = ()
        coverage = None
        ordinary_status = "unavailable"
        contract_version = None
        decision = None
        dimensions = {name: "not_evaluated" for name in ("factual_evidence", "difficulty", "self_contained")}
        issue_statistics = IssueStatisticsV1()
        truncated = False
        reasons: list[str] = []

        if evidence.failure_code:
            ordinary_status = "failed"
            coverage = unmeasured_coverage(
                QualityMetricStatus.FAILED, reason_codes=(evidence.failure_code,),
            )
            reasons.append(evidence.failure_code)
        elif evidence.entry is None and self._review_enabled(bundle) is False:
            ordinary_status = "not_requested"
            coverage = unmeasured_coverage(
                QualityMetricStatus.NOT_REQUESTED, reason_codes=("ORDINARY_REVIEW_NOT_REQUESTED",),
            )
        elif evidence.audit is None:
            ordinary_status = "legacy_unavailable"
            coverage = unmeasured_coverage(
                QualityMetricStatus.LEGACY_UNAVAILABLE,
                reason_codes=("ORDINARY_REVIEW_LEGACY",),
                evidence_mode=QualityEvidenceMode.LEGACY,
            )
        elif ledger is None:
            ordinary_status = "unavailable"
            coverage = unmeasured_coverage(
                QualityMetricStatus.UNAVAILABLE, reason_codes=("ORDINARY_LEDGER_UNAVAILABLE",),
            )
            reasons.append("ORDINARY_LEDGER_UNAVAILABLE")
        else:
            record_version = getattr(getattr(ledger, "binding", None), "version", None)
            contract_version = evidence.audit.schema_version
            final = ledger.observations[-1]
            decision = getattr(final, "decision", None)
            if record_version != resource.version:
                ordinary_status = "unavailable"
                coverage = unmeasured_coverage(
                    QualityMetricStatus.UNAVAILABLE, reason_codes=("ORDINARY_VERSION_MISMATCH",),
                )
                reasons.append("ORDINARY_VERSION_MISMATCH")
            elif getattr(final, "origin", "model_review") == "program_gate":
                ordinary_status = "failed"
                coverage = unmeasured_coverage(
                    QualityMetricStatus.FAILED, reason_codes=("ORDINARY_PROGRAM_GATE_ONLY",),
                )
                reasons.append("ORDINARY_PROGRAM_GATE_ONLY")
            else:
                output = getattr(final, "output", None)
                candidate = _targets_from_output(output)
                if not frozen_targets:
                    ordinary_status = "unavailable"
                    coverage = unmeasured_coverage(
                        QualityMetricStatus.UNAVAILABLE, reason_codes=("COVERAGE_TARGETS_EMPTY",),
                    )
                    reasons.append("COVERAGE_TARGETS_EMPTY")
                elif {item.target_id for item in candidate} != set(frozen_targets):
                    ordinary_status = "unavailable"
                    coverage = unmeasured_coverage(
                        QualityMetricStatus.UNAVAILABLE, reason_codes=("COVERAGE_TARGETS_MISMATCH",),
                    )
                    reasons.append("COVERAGE_TARGETS_MISMATCH")
                elif len(candidate) != len(frozen_targets):
                    ordinary_status = "unavailable"
                    coverage = unmeasured_coverage(
                        QualityMetricStatus.UNAVAILABLE, reason_codes=("COVERAGE_DUPLICATE_TARGET",),
                    )
                    reasons.append("COVERAGE_DUPLICATE_TARGET")
                else:
                    order = {target: index for index, target in enumerate(frozen_targets)}
                    targets = tuple(sorted(candidate, key=lambda item: order[item.target_id]))
                    coverage = measured_coverage(targets)
                    ordinary_status = "complete"
                    dimensions = {name: _dimension(output, name)
                                  for name in ("factual_evidence", "difficulty", "self_contained")}
                    if getattr(evidence.audit, "resources", None):
                        decision = next(
                            (item.decision for item in evidence.audit.resources
                             if item.resource_id == resource.resource_id),
                            decision,
                        )
                    truncated = _ledger_truncated(output, ledger)
                    issue_statistics = _issue_statistics(ledger, truncated=truncated)

        claim = self._claim_quality(
            bundle, resource, claim_requested=claim_requested,
            ordinary_approved=spec is not None and self._ordinary_approved(
                bundle, resource, evidence, ledger, decision,
                dimensions.get("factual_evidence"),
            ),
            ordinary_status=ordinary_status,
        )
        difficulty_fit = DifficultyFitV1(
            dimension_status=dimensions["difficulty"],
            estimated_difficulty=resource.difficulty,
            match_status="not_measured",
        )
        source_binding = self._source_binding(resource)
        availability = (
            QualityAvailability.AVAILABLE
            if coverage.status is QualityMetricStatus.COMPLETE
            and claim.status in {CLAIM_STATUS_COMPLETE, "reference", "not_requested", "not_applicable"}
            else QualityAvailability.PARTIAL
        )
        return ResourceQualityMetricsV1(
            run_id=bundle.run_id,
            resource_spec_id=resource.resource_spec_id,
            resource_id=resource.resource_id,
            resource_version=resource.version,
            resource_type=resource.resource_type,
            topic=resource.topic or "",
            display_order=(
                spec.display_order if spec is not None else 0
            ),
            published=resource.publication_status == "published",
            review_id=resource.review_id,
            coverage=coverage,
            hallucination=claim.hallucination,
            factual_support=claim.support_rate,
            claim=claim,
            ordinary_review=self._ordinary_review(
                status=ordinary_status,
                contract_version=contract_version,
                resource=resource,
                evidence=evidence,
                decision=decision,
                dimensions=dimensions,
                targets=targets,
                truncated=truncated,
            ),
            difficulty_fit=difficulty_fit,
            issue_statistics=issue_statistics,
            source_binding=source_binding,
            target_coverage=targets,
            availability=availability,
            reason_codes=tuple(sorted(set(reasons))),
        )

    def _ordinary_review(
        self,
        *,
        status: str,
        contract_version,
        resource: LearningResource,
        evidence: _ReviewEvidence,
        decision,
        dimensions,
        targets,
        truncated: bool,
    ):
        covered = sum(item.status == "covered" for item in targets) if targets else None
        return OrdinaryReviewQualityV1(
            status=status,
            contract_version=contract_version,
            review_id=evidence.resource_audit.review_id if evidence.resource_audit else None,
            review_step_id=evidence.entry.step_id if evidence.entry else None,
            review_step_sequence=(
                evidence.entry.step_sequence if evidence.entry and evidence.entry.step_sequence >= 0 else None
            ),
            decision=decision,
            factual_evidence=dimensions["factual_evidence"],
            difficulty=dimensions["difficulty"],
            self_contained=dimensions["self_contained"],
            target_total=len(targets) if targets else None,
            covered_target_total=covered,
            missing_target_total=(len(targets) - covered) if targets and covered is not None else None,
            truncated_issue_count=truncated,
            failure_code=evidence.failure_code,
        )

    @staticmethod
    def _frozen_targets(spec) -> tuple[str, ...]:
        if spec is None:
            return ()
        ordered: list[str] = []
        for target in getattr(spec, "knowledge_points", ()) or ():
            if isinstance(target, str) and target and target not in ordered:
                ordered.append(target)
        return tuple(ordered)

    def _review_evidence(self, bundle: QualitySourceBundle, resource: LearningResource) -> _ReviewEvidence:
        entries = {entry.step_id: entry for entry in bundle.audits if entry.run_id == bundle.run_id}
        matched: list[tuple[StepReviewAudit, Any]] = []
        for entry in entries.values():
            if entry.audit is None:
                continue
            record = next(
                (
                    item for item in entry.audit.resources
                    if item.resource_id == resource.resource_id
                    and item.review_id == resource.review_id
                    and (not item.resource_spec_id or item.resource_spec_id == resource.resource_spec_id)
                ),
                None,
            )
            if record is not None:
                matched.append((entry, record))
        # Failed and valid rounds share one timeline. A newer invalid audit
        # must not be hidden by an older valid result for the same resource.
        failed = [
            entries[step.step_id] for step in bundle.steps
            if step.run_id == bundle.run_id and step.step_id in entries
            and entries[step.step_id].failure_code
            and resource.resource_id in (step.resource_ids or ())
        ]
        latest_valid = max(matched, key=lambda item: (item[0].step_sequence, item[0].step_id)) if matched else None
        latest_failed = max(failed, key=lambda item: (item.step_sequence, item.step_id)) if failed else None
        if latest_failed is not None and (
            latest_valid is None or latest_failed.step_sequence >= latest_valid[0].step_sequence
        ):
            entry = latest_failed
            return _ReviewEvidence(
                audit=None, resource_audit=None, entry=entry, failure_code=entry.failure_code,
            )
        if latest_valid is not None:
            entry, record = latest_valid
            return _ReviewEvidence(
                audit=entry.audit, resource_audit=record, entry=entry, failure_code=None,
            )
        return _ReviewEvidence(audit=None, resource_audit=None, entry=None, failure_code=None)

    @staticmethod
    def _exact_ledger(evidence: _ReviewEvidence, resource: LearningResource):
        audit = evidence.audit
        if audit is None:
            return None, None
        for collection, kind in (("resource_ledgers", "resource"), ("lecture_ledgers", "lecture")):
            for ledger in getattr(audit, collection, ()) or ():
                binding = getattr(ledger, "binding", None)
                if binding is None or binding.resource_id != resource.resource_id:
                    continue
                # The binding identity is (run, spec, lineage, resource, type);
                # the resource version is compared before any value is used.
                if (binding.resource_type != resource.resource_type
                        or binding.run_id != resource.run_id
                        or binding.resource_spec_id != resource.resource_spec_id
                        or binding.lineage_id != resource.resource_family_id):
                    continue
                return ledger, kind
        return None, None

    def _ordinary_approved(
        self,
        bundle: QualitySourceBundle,
        resource: LearningResource,
        evidence: _ReviewEvidence,
        ledger,
        decision,
        factual_dimension,
    ) -> bool:
        """Whether the ordinary review passed with a clean factual verdict."""
        if evidence.failure_code:
            return False
        conflicting = self._conflicting_persisted_risk(resource, evidence)
        if evidence.audit is not None and ledger is not None:
            if decision != "approve" or factual_dimension != "pass":
                return False
            return not conflicting
        if evidence.audit is not None and ledger is None and (
            getattr(evidence.audit, "resource_ledgers", None)
            or getattr(evidence.audit, "lecture_ledgers", None)
        ):
            return False
        persisted = self._persisted_review(bundle, resource)
        if persisted is None:
            return False
        status = normalize_review_status(getattr(persisted, "status", ""))
        if not review_status_is_approved(status):
            return False
        return not conflicting

    @staticmethod
    def _persisted_review(bundle: QualitySourceBundle, resource: LearningResource):
        record = dict(bundle.reviews).get(resource.resource_id)
        if record is None:
            return None
        if getattr(record, "review_id", None) != resource.review_id:
            return None
        return record

    @staticmethod
    def _conflicting_persisted_risk(resource: LearningResource, evidence: _ReviewEvidence) -> bool:
        if evidence.resource_audit is not None:
            if evidence.resource_audit.decision != "approve":
                return True
            if evidence.resource_audit.semantic_status == "failed":
                return True
        return False

    def _claim_quality(
        self,
        bundle: QualitySourceBundle,
        resource: LearningResource,
        *,
        claim_requested: bool | None,
        ordinary_approved: bool,
        ordinary_status: str,
    ) -> ClaimQualityV1:
        if claim_requested is None:
            return claim_quality(None, requested=False, status="unavailable",
                                 review_id=resource.review_id,
                                 reason_codes=("CLAIM_REQUEST_UNKNOWN",))
        if not claim_requested:
            if ordinary_approved and self._review_enabled(bundle) is True:
                return claim_quality(
                    None, requested=False, status="reference",
                    review_id=resource.review_id,
                    reason_codes=("ORDINARY_REVIEW_APPROVED_REFERENCE",),
                )
            status = {
                "failed": "failed",
                "legacy_unavailable": "legacy_unavailable",
                "not_requested": "not_requested",
            }.get(ordinary_status, "not_applicable")
            return claim_quality(
                None, requested=False, status=status,
                review_id=resource.review_id,
                not_applicable=status == "not_applicable",
                failure_code="ORDINARY_REVIEW_NOT_APPROVED" if status == "failed" else None,
                reason_codes=("ORDINARY_REVIEW_NOT_APPROVED",),
            )

        binding = (bundle.run_id, resource.resource_id, resource.version, resource.review_id)
        claims = [
            item for item in bundle.claims
            if (item.run_id, item.resource_id, item.resource_version, item.review_id) == binding
        ]
        judgements = [
            item for item in bundle.judgements
            if (item.run_id, item.resource_id, item.resource_version, item.review_id) == binding
        ]
        projection = bundle.checkpoints[-1].state_projection if bundle.checkpoints else {}
        if (resource.resource_id in set(projection.get("claim_failed_resource_ids") or ())
                or projection.get("claim_check_status") == "failed"):
            return claim_quality(None, requested=True, status="failed",
                                 review_id=resource.review_id, failed=True,
                                 failure_code="CLAIM_AUDIT_FAILED")
        if projection.get("claim_check_status") == "pending":
            return claim_quality(None, requested=True, status="pending",
                                 review_id=resource.review_id, pending=True)
        sessions = [
            item for item in bundle.supplement_sessions
            if (item.resource_id, item.resource_version, item.review_id)
            == (resource.resource_id, resource.version, resource.review_id)
        ]
        supplements = [
            item for item in bundle.supplement_judgements
            if (item.resource_id, item.resource_version, item.review_id)
            == (resource.resource_id, resource.version, resource.review_id)
        ]
        try:
            resolution = resolve_effective_claim_judgements(
                judgements, sessions, supplements,
            )
        except ClaimResolutionConflict:
            return claim_quality(
                None, requested=True, status="incomplete",
                review_id=resource.review_id, conflict=True,
                reason_codes=("CLAIM_JUDGEMENT_CONFLICT",),
            )
        effective = resolution.judgements
        # Round-0 disagreement on a substituted Claim is historical, not a data
        # conflict; every other Claim keeps the original strict check.
        if self._conflicting_judgements(
            claims,
            [
                item for item in judgements
                if item.claim_id not in set(resolution.substituted_claim_ids)
            ],
        ):
            return claim_quality(
                None, requested=True, status="incomplete",
                review_id=resource.review_id, conflict=True,
                reason_codes=("CLAIM_JUDGEMENT_CONFLICT",),
            )
        if claims:
            summary = compute_claim_metric(claims, effective.values())
            if summary.metric_status is ClaimMetricStatus.INCOMPLETE:
                return claim_quality(
                    summary, requested=True, status="incomplete",
                    review_id=resource.review_id,
                    reason_codes=("CLAIM_JUDGEMENT_INCOMPLETE",),
                )
            if summary.metric_status is ClaimMetricStatus.NOT_APPLICABLE:
                return claim_quality(
                    summary, requested=True, status="not_applicable",
                    review_id=resource.review_id, not_applicable=True,
                    reason_codes=("NO_FACTUAL_CLAIMS",),
                )
            return claim_quality(
                summary, requested=True, status="complete", review_id=resource.review_id,
            )

        failed_ids = set(projection.get("claim_failed_resource_ids") or ())
        skipped_ids = set(projection.get("assessment_claim_skipped_resource_ids") or ())
        if resource.resource_id in failed_ids:
            return claim_quality(
                None, requested=True, status="failed", review_id=resource.review_id,
                failed=True, failure_code="CLAIM_AUDIT_FAILED",
            )
        if resource.resource_id in skipped_ids:
            return claim_quality(
                None, requested=True, status="not_applicable", review_id=resource.review_id,
                not_applicable=True, reason_codes=("CLAIM_CHECK_NOT_APPLICABLE",),
            )
        if projection.get("claim_check_status") == "pending":
            return claim_quality(
                None, requested=True, status="pending", review_id=resource.review_id, pending=True,
            )
        # Requested, no rows, no durable marker: unknown, not not_applicable.
        return claim_quality(
            None, requested=True, status="unavailable", review_id=resource.review_id,
            reason_codes=("CLAIM_FACTS_UNAVAILABLE",),
        )

    @staticmethod
    def _conflicting_judgements(claims: Iterable[ClaimRecord], judgements: Iterable[ClaimJudgement]) -> bool:
        claim_ids = {item.claim_id for item in claims}
        seen: dict[str, str] = {}
        for judgement in judgements:
            if judgement.status is not ClaimJudgementStatus.COMPLETED:
                continue
            if judgement.claim_id not in claim_ids:
                continue
            fingerprint = str(getattr(judgement.verdict, "value", judgement.verdict))
            previous = seen.get(judgement.claim_id)
            if previous is not None and previous != fingerprint:
                return True
            seen[judgement.claim_id] = fingerprint
        return False

    @staticmethod
    def _source_binding(resource: LearningResource) -> SourceBindingQualityV1:
        refs = list(resource.source_refs or ())
        verified = [
            ref for ref in refs
            if ref.provenance_status == "verified" and ref.evidence_id and ref.knowledge_base_id
            and ref.doc_id and ref.document_version and ref.chunk_id
        ]
        if not refs:
            return SourceBindingQualityV1(
                status="not_measured", reason_codes=("SOURCE_REF_MISSING",),
            )
        status = "complete" if len(verified) == len(refs) else "partial" if verified else "not_measured"
        return SourceBindingQualityV1(
            status=status,
            source_ref_total=len(refs),
            verified_ref_total=len(verified),
            unique_document_total=len({ref.doc_id for ref in verified}),
            reason_codes=() if status == "complete" else ("SOURCE_REF_PARTIALLY_VERIFIED",),
        )


__all__ = [
    "ResourceQualityNotFound",
    "ResourceQualityQueryService",
]
