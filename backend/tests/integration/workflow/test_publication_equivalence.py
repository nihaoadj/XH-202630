"""Behavioural equivalence for the extracted automatic publication decision.

The expectations in ``fixtures/publication/policy_v1.json`` were recorded by
running the unmodified ``decide_node`` before the extraction.  Every case is a
synthetic, non-sensitive state; no live model, database or clock is involved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.agents.resource_workflows.learning_documents import workflow as workflow_module
from app.agents.resource_workflows.learning_documents.workflow import decide_node
from app.agents.shared.policies import (
    PublicationInputs,
    PublicationReason,
    resolve_publication,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.workflow import ResourceStatus

FIXTURE = Path(__file__).resolve().parents[2] / "fixtures" / "publication" / "policy_v1.json"
FROZEN_NOW = datetime(2026, 11, 7, 9, 30, tzinfo=timezone.utc)


class _FrozenDatetime(datetime):
    """Freeze the node's publication timestamp without touching other clocks."""

    @classmethod
    def now(cls, tz=None):  # noqa: ANN001
        return FROZEN_NOW if tz is not None else FROZEN_NOW.replace(tzinfo=None)


def _cases() -> list[dict]:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert payload["schema_version"] == "1.0"
    return payload["cases"]


def _build_state(case: dict) -> dict:
    state = {key: value for key, value in case["state"].items()}
    state["generated_resources"] = [
        LearningResource(**item) for item in case["resources"]
    ]
    # Deep-copy the mutable containers so one case cannot leak into the next.
    state["resource_executions"] = [dict(item) for item in case["state"]["resource_executions"]]
    state["review_result"] = dict(case["state"]["review_result"])
    state["review_result"]["review_ids"] = dict(state["review_result"]["review_ids"])
    state["review_result"]["issues"] = [dict(item) for item in state["review_result"]["issues"]]
    return state


def _apply_settings(monkeypatch, case: dict) -> None:
    settings = dict(case["settings"])
    monkeypatch.setattr(
        workflow_module, "get_settings", lambda: SimpleNamespace(**settings)
    )
    monkeypatch.setattr(workflow_module, "datetime", _FrozenDatetime)


def _run_node(monkeypatch, case: dict):
    _apply_settings(monkeypatch, case)
    return decide_node(_build_state(case))


def _observed(result) -> dict:
    return {
        "resources": [
            {
                "resource_id": item.resource_id,
                "review_status": item.review_status,
                "publication_status": item.publication_status,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "claim_publish_decision_pending": item.claim_publish_decision_pending,
                "claim_degraded_publish": item.claim_degraded_publish,
                "claim_warning_publish": item.claim_warning_publish,
                "claim_factual_pass_rate": item.claim_factual_pass_rate,
                "review_id": item.review_id,
                "claim_metric_status": item.claim_metric_status,
                "claim_publish_decision": item.claim_publish_decision,
            }
            for item in result["generated_resources"]
        ],
        "resource_executions": [
            {
                "resource_id": item.get("resource_id"),
                "resource_execution_state": item.get("resource_execution_state"),
                "review_id": item.get("review_id"),
            }
            for item in result["resource_executions"]
        ],
        "workflow_status": result["workflow_status"],
        "claim_check_status": result["claim_check_status"],
        "final_decision": result["final_decision"],
    }


# ``ResourceStatus`` values used when a resource has no recognised per-resource
# decision; this reproduces only the caller's run-level status derivation.
_FALLBACK_APPROVED = ResourceStatus.APPROVED
_FALLBACK_REJECTED = ResourceStatus.REJECTED
_FALLBACK_REVIEW = ResourceStatus.HUMAN_REVIEW


def _fallback_status(case: dict) -> ResourceStatus:
    state = case["state"]
    decision = state["review_result"]["decision"]
    strict = state.get("generation_mode") == "strict" and bool(
        state.get("errors") or any(
            item.get("status") == "degraded" for item in state.get("trace") or []
        )
    )
    if decision == "approve" and not strict:
        return _FALLBACK_APPROVED
    if decision == "reject":
        return _FALLBACK_REJECTED
    return _FALLBACK_REVIEW


_DECISION_FROM_RESOURCE_STATUS = {
    ResourceStatus.APPROVED.value: "approve",
    ResourceStatus.REJECTED.value: "reject",
    ResourceStatus.HUMAN_REVIEW.value: "human_review",
    ResourceStatus.REVISION_REQUESTED.value: "revise",
}


def _inputs_for(case: dict, resource: LearningResource) -> PublicationInputs:
    """Adapt one case to the pure-function contract.

    Only field lookups the node itself performs are reproduced here; no branch
    of the publication decision is duplicated.
    """

    state = case["state"]
    settings = case["settings"]
    review = state["review_result"]
    per_resource = state.get("resource_review_results", {}).get(resource.resource_id) or {}
    item_decision = str(
        per_resource.get("decision")
        or _DECISION_FROM_RESOURCE_STATUS.get(resource.review_status, review["decision"])
    )
    metric = state.get("claim_metrics", {}).get(resource.resource_id, {})
    issues = [item for item in review.get("issues", []) if isinstance(item, dict)]
    problem_ids = {
        str(item.get("resource_id")) for item in issues if item.get("resource_id")
    }
    locked_ids = {
        item["resource_id"]
        for item in case["resources"]
        if item.get("review_status") == ResourceStatus.HUMAN_REVIEW.value
    } | {
        str(item["resource_id"])
        for item in state["resource_executions"]
        if item.get("resource_id")
        and (
            item.get("resource_execution_state") == ResourceStatus.HUMAN_REVIEW.value
            or item.get("validation_status") == "failed"
        )
    }
    return PublicationInputs(
        item_decision=item_decision,
        fallback_status=_fallback_status(case),
        is_locked=resource.resource_id in locked_ids,
        strict_with_degradation=(
            state.get("generation_mode") == "strict"
            and bool(state.get("errors") or state.get("trace"))
        ),
        include_claim_check=bool(state.get("include_claim_check", False)),
        is_claim_eligible=resource.resource_id in set(state.get("claim_eligible_resource_ids", [])),
        claim_failed=resource.resource_id in set(state.get("claim_failed_resource_ids", [])),
        has_claim_problem=resource.resource_id in problem_ids,
        claim_metric_status=metric.get("metric_status"),
        factual_claim_total=int(metric.get("factual_claim_total", 0) or 0),
        supported_claim_total=int(metric.get("supported_claim_total", 0) or 0),
        contradicted_claim_total=int(metric.get("contradicted_claim_total", 0) or 0),
        not_in_evidence_claim_total=int(metric.get("not_in_evidence_claim_total", 0) or 0),
        allow_partial_claim_publish=bool(settings["claim_partial_publish"]),
        claim_user_review_enabled=bool(settings["claim_user_review_enabled"]),
        claim_user_review_min_factual_pass_rate=float(
            settings["claim_user_review_min_factual_pass_rate"]
        ),
    )


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["case_id"])
def test_decide_node_matches_recorded_baseline(monkeypatch, case):
    observed = _observed(_run_node(monkeypatch, case))
    assert observed == case["expected"]


@pytest.mark.parametrize("case", _cases(), ids=lambda case: case["case_id"])
def test_resolver_matches_node_decision(monkeypatch, case):
    observed = _observed(_run_node(monkeypatch, case))
    by_id = {item["resource_id"]: item for item in observed["resources"]}
    for resource in _build_state(case)["generated_resources"]:
        decision = resolve_publication(_inputs_for(case, resource))
        recorded = by_id[resource.resource_id]
        assert decision.review_status.value == recorded["review_status"]
        assert decision.publish == (recorded["publication_status"] == "published")
        assert decision.claim_publish_decision_pending == recorded["claim_publish_decision_pending"]
        assert decision.claim_degraded_publish == recorded["claim_degraded_publish"]
        assert decision.factual_pass_rate == recorded["claim_factual_pass_rate"]
        assert isinstance(decision.reason, PublicationReason)


def test_strict_degradation_baseline_keeps_item_level_approval(monkeypatch):
    """The strict flag only drives the run-level fallback status.

    Per-resource terminal state still follows the item's own ordinary decision
    because the historical node re-assigned it after the strict branch.  The
    extraction must preserve that observable result; fixing strict priority is
    explicitly out of scope for T47.
    """

    case = next(item for item in _cases() if item["case_id"] == "strict_with_degradation")
    result = _run_node(monkeypatch, case)
    resource = result["generated_resources"][0]
    assert resource.review_status == "approved"
    assert resource.publication_status == "published"
    assert result["workflow_status"] == "completed"

    inputs = _inputs_for(case, _build_state(case)["generated_resources"][0])
    assert inputs.strict_with_degradation is True
    assert inputs.item_decision == "approve"
    # The flag did not block this resource, so the reason reports the path that
    # actually decided the outcome instead of a strict gate that never fired.
    assert resolve_publication(inputs).reason is PublicationReason.APPROVED


def test_two_resources_are_decided_independently(monkeypatch):
    case = next(item for item in _cases() if item["case_id"] == "two_resources_isolated")
    result = _run_node(monkeypatch, case)
    statuses = {item.resource_id: item.review_status for item in result["generated_resources"]}
    assert statuses == {"res-1": "approved", "res-2": "rejected"}
    publications = {
        item.resource_id: item.publication_status for item in result["generated_resources"]
    }
    assert publications == {"res-1": "published", "res-2": "unpublished"}
