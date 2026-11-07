"""Unit coverage for the read-only publication aggregate."""

from __future__ import annotations

import pytest

from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.generation.progress import (
    PublishCompleteness,
    PublishIncompleteReason,
    RunPublishSummary,
)
from app.models.learning_documents.schemas import LearningResource
from app.services.learning_documents.publication_summary import (
    aggregate_publication_summary,
)

RUN_ID = "run-t47"


def _spec(spec_id: str, resource_type: str = "讲义", **overrides) -> ResourceSpecRecord:
    payload = {
        "resource_spec_id": spec_id,
        "run_id": RUN_ID,
        "resource_type": resource_type,
        "learning_objective": f"覆盖 {spec_id}",
        "difficulty": "初级",
        "representations": [{"representation": "text"}],
        "display_order": 0,
    }
    payload.update(overrides)
    return ResourceSpecRecord(**payload)


def _execution(spec_id: str, *, resource_id=None, run_id=RUN_ID, state="generated") -> ResourceExecutionRecord:
    return ResourceExecutionRecord(
        run_id=run_id,
        resource_spec_id=spec_id,
        resource_type="讲义",
        state=state,
        resource_id=resource_id,
        agent_name="TextResourceAgent",
        prompt_version="v1",
        artifact_format="markdown",
    )


def _resource(resource_id: str, *, spec_id=None, run_id=RUN_ID, published=False, version=1, **overrides) -> LearningResource:
    payload = {
        "resource_id": resource_id,
        "resource_type": "讲义",
        "difficulty": "初级",
        "knowledge_points": ["kp-1"],
        "source_refs": [],
        "run_id": run_id,
        "resource_spec_id": spec_id,
        "publication_status": "published" if published else "unpublished",
        "version": version,
    }
    payload.update(overrides)
    return LearningResource(**payload)


def _aggregate(request_types=("讲义", "实操指南", "分阶测试题"), specs=(), executions=(), resources=()):
    request = {"resource_types": list(request_types)} if request_types else None
    return aggregate_publication_summary(
        run_id=RUN_ID,
        request_payload=request,
        specs=list(specs),
        executions=list(executions),
        resources=list(resources),
    )


def test_three_requested_two_published_one_failed_without_artifact():
    specs = [_spec("spec-a", "讲义"), _spec("spec-b", "实操指南"), _spec("spec-c", "分阶测试题")]
    executions = [
        _execution("spec-a", resource_id="res-a"),
        _execution("spec-b", resource_id="res-b"),
        _execution("spec-c", state="failed"),
    ]
    resources = [
        _resource("res-a", spec_id="spec-a", published=True),
        _resource("res-b", spec_id="spec-b", published=True),
    ]

    summary = _aggregate(specs=specs, executions=executions, resources=resources)

    assert summary.total == 3
    assert summary.published == 2
    assert summary.unpublished == 1
    assert summary.pending_review == 0
    assert summary.completeness is PublishCompleteness.COMPLETE
    assert summary.incomplete_reasons == []


def test_all_published_is_complete():
    specs = [_spec("spec-a"), _spec("spec-b", "实操指南")]
    summary = _aggregate(
        request_types=("讲义", "实操指南"),
        specs=specs,
        executions=[_execution("spec-a", resource_id="res-a"), _execution("spec-b", resource_id="res-b")],
        resources=[
            _resource("res-a", spec_id="spec-a", published=True),
            _resource("res-b", spec_id="spec-b", published=True),
        ],
    )
    assert (summary.total, summary.published, summary.unpublished) == (2, 2, 0)
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_multiple_versions_of_one_spec_count_once_and_prefer_published_version():
    specs = [_spec("spec-a")]
    executions = [_execution("spec-a", resource_id="res-latest")]
    resources = [
        _resource("res-old", spec_id="spec-a", published=True, version=1),
        _resource("res-mid", spec_id="spec-a", published=True, version=2),
        _resource("res-latest", spec_id="spec-a", published=False, version=3),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=executions, resources=resources)
    assert summary.total == 1
    assert summary.published == 1
    assert summary.pending_review == 0
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_readable_old_version_with_pending_current_attempt_is_not_pending():
    specs = [_spec("spec-a")]
    executions = [_execution("spec-a", resource_id="res-latest")]
    resources = [
        _resource("res-old", spec_id="spec-a", published=True, version=1),
        _resource(
            "res-latest", spec_id="spec-a", published=False, version=2,
            claim_publish_decision_pending=True,
        ),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=executions, resources=resources)
    assert summary.published == 1
    assert summary.pending_review == 0


def test_pending_review_counts_only_unpublished_pending_slots():
    specs = [_spec("spec-a"), _spec("spec-b", "实操指南")]
    executions = [_execution("spec-a", resource_id="res-a"), _execution("spec-b", resource_id="res-b")]
    resources = [
        _resource("res-a", spec_id="spec-a", published=False, claim_publish_decision_pending=True),
        _resource("res-b", spec_id="spec-b", published=False),
    ]
    summary = _aggregate(
        request_types=("讲义", "实操指南"), specs=specs, executions=executions, resources=resources
    )
    assert summary.published == 0
    assert summary.unpublished == 2
    assert summary.pending_review == 1
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_specs_not_yet_materialised_use_request_denominator_and_stay_partial():
    summary = _aggregate(request_types=("讲义", "实操指南", "分阶测试题"))
    assert summary.total == 3
    assert summary.published == 0
    # Coverage is not proven while specs are missing, so the derived
    # unpublished remainder must stay unknown rather than claim 3.
    assert summary.unpublished is None
    assert summary.pending_review == 0
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.incomplete_reasons == [PublishIncompleteReason.SPEC_REQUEST_MISMATCH]


def test_request_only_slot_keeps_total_while_another_spec_is_published():
    specs = [_spec("spec-a")]
    executions = [_execution("spec-a", resource_id="res-a")]
    resources = [_resource("res-a", spec_id="spec-a", published=True)]
    summary = _aggregate(
        request_types=("讲义", "实操指南"), specs=specs, executions=executions, resources=resources
    )
    assert summary.total == 2
    assert summary.published == 1
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.incomplete_reasons == [PublishIncompleteReason.SPEC_REQUEST_MISMATCH]


def test_missing_request_keeps_confirmed_count_but_unknown_total():
    summary = aggregate_publication_summary(
        run_id=RUN_ID,
        request_payload=None,
        specs=[_spec("spec-a")],
        executions=[_execution("spec-a", resource_id="res-a")],
        resources=[_resource("res-a", spec_id="spec-a", published=True)],
    )
    assert summary.total is None
    assert summary.published == 1
    assert summary.unpublished is None
    assert summary.pending_review is None
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.incomplete_reasons == [PublishIncompleteReason.REQUEST_MISSING]


def test_unloaded_collection_reports_unavailable_not_zero():
    summary = aggregate_publication_summary(
        run_id=RUN_ID,
        request_payload={"resource_types": ["讲义"]},
        specs=[],
        executions=None,
        resources=[],
    )
    assert summary.completeness is PublishCompleteness.UNAVAILABLE
    assert summary.total is None
    assert summary.published is None
    assert summary.incomplete_reasons == [PublishIncompleteReason.REPOSITORY_UNAVAILABLE]


def test_child_run_does_not_borrow_parent_publication():
    specs = [_spec("spec-child")]
    executions = [_execution("spec-child", resource_id="res-child")]
    resources = [
        _resource("res-child", spec_id="spec-child", published=False),
        _resource("res-parent", spec_id="spec-child", run_id="run-parent", published=True),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=executions, resources=resources)
    assert summary.total == 1
    assert summary.published == 0
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_unknown_logical_identity_is_partial_instead_of_merged_by_type():
    specs = [_spec("spec-a")]
    resources = [
        _resource("res-legacy", spec_id=None, published=True),
        _resource("res-second", spec_id=None, published=True),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=[], resources=resources)
    assert summary.total == 1
    assert summary.published == 0
    assert summary.pending_review is None
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert PublishIncompleteReason.LOGICAL_IDENTITY_MISSING in summary.incomplete_reasons


def test_family_chain_restores_identity_without_spec_id():
    specs = [_spec("spec-a", resource_family_id="family-a")]
    resources = [
        _resource("res-v1", spec_id=None, resource_family_id="family-a", published=True, version=1),
        _resource("res-v2", spec_id=None, resource_family_id="family-a", version=2),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=[], resources=resources)
    assert summary.total == 1
    assert summary.published == 1
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_parent_chain_restores_identity_but_cycle_is_a_conflict():
    specs = [_spec("spec-a")]
    linked = [
        _resource("res-old", spec_id="spec-a", published=True, version=1),
        _resource("res-new", spec_id=None, parent_resource_id="res-old", version=2),
    ]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=[], resources=linked)
    assert summary.published == 1
    assert summary.completeness is PublishCompleteness.COMPLETE

    cyclic = [
        _resource("res-x", spec_id=None, parent_resource_id="res-y"),
        _resource("res-y", spec_id=None, parent_resource_id="res-x"),
    ]
    conflicted = _aggregate(request_types=("讲义",), specs=specs, executions=[], resources=cyclic)
    assert conflicted.published == 0
    assert conflicted.completeness is PublishCompleteness.PARTIAL
    assert conflicted.incomplete_reasons == [PublishIncompleteReason.LINEAGE_CONFLICT]


def test_dangling_execution_reference_is_partial():
    specs = [_spec("spec-a")]
    executions = [_execution("spec-a", resource_id="res-missing")]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=executions, resources=[])
    assert summary.total == 1
    assert summary.published == 0
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.incomplete_reasons == [PublishIncompleteReason.RESOURCE_REFERENCE_MISSING]


def test_missing_current_reference_keeps_pending_unknown():
    summary = _aggregate(
        request_types=("讲义",), specs=[_spec("spec-a")],
        executions=[_execution("spec-a", resource_id="missing")], resources=[],
    )
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.pending_review is None


def test_execution_cannot_borrow_a_siblings_pending_resource():
    summary = _aggregate(
        request_types=("讲义", "实操指南"),
        specs=[_spec("spec-a"), _spec("spec-b", "实操指南")],
        executions=[
            _execution("spec-a", resource_id="res-b"),
            _execution("spec-b", resource_id="res-b"),
        ],
        resources=[_resource("res-b", spec_id="spec-b", claim_publish_decision_pending=True)],
    )
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.pending_review is None
    assert summary.unpublished is None
    assert summary.incomplete_reasons == [PublishIncompleteReason.LINEAGE_CONFLICT]


def test_conflicting_execution_keeps_independent_published_fact():
    summary = _aggregate(
        request_types=("讲义", "实操指南"),
        specs=[_spec("spec-a"), _spec("spec-b", "实操指南")],
        executions=[_execution("spec-a", resource_id="res-b")],
        resources=[
            _resource("res-a", spec_id="spec-a", published=True),
            _resource("res-b", spec_id="spec-b", published=True),
        ],
    )
    assert summary.published == 2
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.pending_review is None
    assert summary.incomplete_reasons == [PublishIncompleteReason.LINEAGE_CONFLICT]


def test_type_alias_is_canonicalised_but_specs_are_not_merged():
    specs = [_spec("spec-a", "讲义")]
    summary = _aggregate(
        request_types=("定制讲义",),
        specs=specs,
        executions=[_execution("spec-a", resource_id="res-a")],
        resources=[_resource("res-a", spec_id="spec-a", published=True)],
    )
    assert summary.total == 1
    assert summary.published == 1
    assert summary.completeness is PublishCompleteness.COMPLETE


def test_duplicate_spec_per_type_is_a_scope_mismatch():
    specs = [_spec("spec-a", "讲义"), _spec("spec-b", "讲义")]
    summary = _aggregate(request_types=("讲义",), specs=specs, executions=[], resources=[])
    assert summary.total == 2
    assert summary.completeness is PublishCompleteness.PARTIAL
    assert summary.incomplete_reasons == [PublishIncompleteReason.SPEC_REQUEST_MISMATCH]


@pytest.mark.parametrize("reverse", [False, True])
def test_result_is_independent_of_input_order_and_inputs_are_not_mutated(reverse):
    specs = [_spec("spec-a"), _spec("spec-b", "实操指南")]
    executions = [_execution("spec-a", resource_id="res-a"), _execution("spec-b", resource_id="res-b")]
    resources = [
        _resource("res-a", spec_id="spec-a", published=True),
        _resource("res-b", spec_id="spec-b"),
    ]
    ordered = dict(
        specs=list(reversed(specs)) if reverse else list(specs),
        executions=list(reversed(executions)) if reverse else list(executions),
        resources=list(reversed(resources)) if reverse else list(resources),
    )
    snapshot = {name: [item.model_dump() for item in items] for name, items in ordered.items()}
    summary = _aggregate(request_types=("讲义", "实操指南"), **ordered)
    assert summary.total == 2 and summary.published == 1
    assert {name: [item.model_dump() for item in items] for name, items in ordered.items()} == snapshot


def test_summary_is_a_valid_contract_object():
    specs = [_spec("spec-a")]
    summary = _aggregate(
        request_types=("讲义",),
        specs=specs,
        executions=[_execution("spec-a", resource_id="res-a")],
        resources=[_resource("res-a", spec_id="spec-a", published=True)],
    )
    assert isinstance(summary, RunPublishSummary)
    assert summary.model_dump(mode="json") == {
        "schema_version": "1.0",
        "total": 1,
        "published": 1,
        "unpublished": 0,
        "pending_review": 0,
        "completeness": "complete",
        "incomplete_reasons": [],
    }
