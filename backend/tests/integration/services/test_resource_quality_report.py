"""Report integration for the T48 versioned quality block.

The report consumes the same projection the run endpoint serves; it never
recomputes a metric.  These tests pin the wiring guarantees:

* only visible published text resources enter the aggregation;
* missing source capability keeps unknown resources in the denominator;
* actual database/program errors preserve their error semantics;
* the additive fields are part of the ``text_resources`` revision group, so a
  new quality result cannot hide behind an unchanged resource timestamp;
* the payload still validates against the public report contract.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.audit.quality_read import NATIVE_MEMORY, QualitySourceBundle
from app.db.feedback.feedback_loop_repository import MemoryFeedbackLoopRepository
from app.db.feedback.repository import MemoryFeedbackRepository
from app.db.learners.repository import create_learner_repository
from app.db.learning_documents.memory import MemoryResourceRepository
from app.models.learning_documents.schemas import LearnerProfile, LearningResource
from app.models.reports.contracts import ReportResponse
from app.services.reports.reports import ReportService
from app.services.reports.snapshots import revision_parts
from app.services.reviews.quality_query import ResourceQualityQueryService

LEARNER_ID = "learner-quality-report"
RUN_ID = "run-quality-report"


class _BundleQualityService(ResourceQualityQueryService):
    """Feed the report a deterministic bundle instead of a second data source."""

    def __init__(self, bundles):
        super().__init__(audit_repository=None, resource_repository=None)
        self._bundles = bundles
        self.summarized: list[tuple[str, ...]] = []

    def _load(self, run_id: str) -> QualitySourceBundle:
        return self._bundles[run_id]

    def summarize_items(self, items):
        self.summarized.append(tuple(item.resource_id for item in items))
        return super().summarize_items(items)


class _BrokenQualityService:
    def items_for_runs(self, run_ids):
        raise RuntimeError("quality backend unavailable")

    def summarize_items(self, items):  # pragma: no cover - never reached
        raise AssertionError("summarize must not be called after a failed read")


def _profile() -> LearnerProfile:
    return LearnerProfile(
        learner_id=LEARNER_ID, learner_type="student", education="本科",
        major="软件工程", knowledge_base_id="kb-1", learning_goal="通过考试",
    )


def _resource(resource_id: str, *, status: str = "published", version: int = 1) -> LearningResource:
    return LearningResource(
        resource_id=resource_id, resource_type="讲义", difficulty="中级", topic="T48",
        content_text="内容", knowledge_points=["node-1"], source_refs=[],
        run_id=RUN_ID, resource_spec_id=f"spec-{resource_id}", version=version,
        publication_status=status,
    )


def _service(resources: list[LearningResource], quality) -> ReportService:
    learners = create_learner_repository(db_type="memory")
    learners.save(_profile())
    repository = MemoryResourceRepository()
    for resource in resources:
        repository.save(resource, LEARNER_ID, "T48", run_id=RUN_ID)
    return ReportService(
        repository,
        MemoryFeedbackRepository(),
        MemoryFeedbackLoopRepository(learners),
        quality_service=quality,
    )


def test_report_projects_quality_for_visible_text_resources_only():
    visible = _resource("resource-visible")
    legacy = _resource("resource-legacy", status="unpublished")
    quality = _BundleQualityService({
        RUN_ID: QualitySourceBundle(
            run_id=RUN_ID, read_mode=NATIVE_MEMORY,
            resources=(visible, legacy),
            request_snapshot={"include_review": True, "include_claim_check": False},
        ),
    })
    report = _service([visible, legacy], quality).build_report(_profile())

    summary = report["resource_quality_summary"]
    assert summary is not None
    assert summary.resource_total == 1
    assert [item.resource_id for item in report["recent_resource_quality"]] == [
        "resource-visible",
    ]
    # The aggregation input is exactly the visible set, never the whole run.
    assert quality.summarized
    assert all(entry == ("resource-visible",) for entry in quality.summarized)
    # The resource itself is a legacy-missing row; the aggregate therefore
    # refuses to present a rate and stays explicitly incomplete.
    assert summary.coverage.value is None
    assert summary.coverage.status.value == "incomplete"
    assert summary.coverage_buckets.legacy_unavailable == 1

    # The legacy block is untouched and the additive block validates.
    assert "resource_credibility_summary" in report
    validated = ReportResponse.model_validate(report)
    assert validated.resource_quality_summary.resource_total == 1
    assert validated.recent_resource_quality[0].resource_id == "resource-visible"


def test_quality_read_failure_preserves_error_contract():
    resource = _resource("resource-visible")
    with pytest.raises(RuntimeError, match="quality backend unavailable"):
        _service([resource], _BrokenQualityService()).build_report(_profile())


def test_missing_bundle_resources_and_legacy_no_run_stay_in_denominator():
    visible = _resource("visible")
    legacy = _resource("legacy").model_copy(update={"run_id": None})
    quality = _BundleQualityService({RUN_ID: QualitySourceBundle(run_id=RUN_ID, read_mode=NATIVE_MEMORY)})
    result = _service([], quality)._resource_quality([visible, legacy], order=[])
    assert result["summary"].resource_total == 2
    assert result["summary"].coverage.status.value == "incomplete"
    assert len(result["items"]) == 2



def test_new_quality_values_change_the_text_resources_revision_group():
    resource = _resource("resource-visible")
    base = _service(
        [resource],
        _BundleQualityService({
            RUN_ID: QualitySourceBundle(
                run_id=RUN_ID, read_mode=NATIVE_MEMORY, resources=(resource,),
            ),
        }),
    ).build_report(_profile())
    # Same report with a different quality block (for example a new review
    # round) must move the group hash even when the resource row is identical.
    altered = dict(base)
    altered["recent_resource_quality"] = []
    altered["resource_quality_summary"] = None

    assert revision_parts(base)["text_resources"] != revision_parts(altered)["text_resources"]
    # Unrelated groups stay stable.
    assert revision_parts(base)["profile"] == revision_parts(altered)["profile"]
    assert revision_parts(base)["mastery"] == revision_parts(altered)["mastery"]


def test_report_quality_fields_are_absent_when_no_service_is_configured():
    resource = _resource("resource-visible")
    report = _service([resource], None).build_report(_profile())
    assert report["resource_quality_summary"] is None
    assert report["recent_resource_quality"] == []
    ReportResponse.model_validate(report)
