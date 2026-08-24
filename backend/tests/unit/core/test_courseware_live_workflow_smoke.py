"""Contract tests for the bounded, normal-path live workflow smoke."""

from types import SimpleNamespace

import pytest
from langchain_core.messages import HumanMessage

from app.core.courseware.live_workflow_smoke import (
    LIVE_COMBINATIONS,
    LiveWorkflowBudgetExceeded,
    LiveWorkflowBudget,
    _RecordingGateway,
    _outcome_counts,
    acceptance_report_status,
    redact_workflow_record,
)


def test_live_workflow_smoke_has_ten_fixed_combinations_and_redacts_payloads():
    assert len(LIVE_COMBINATIONS) == 10
    assert [item["id"] for item in LIVE_COMBINATIONS] == [
        "lecture_only",
        "lecture_practice_assessment",
        "five_resource_types",
        "repair_revision_candidate",
        "lecture_checklist",
        "lecture_case",
        "practice_case",
        "assessment_checklist",
        "all_sources_repair",
        "localized_feedback_repair",
    ]
    record = redact_workflow_record({
        "run_id": "cw_secret-run-id",
        "warnings": [{"message": "raw prompt should not survive"}],
        "artifact_sha256": "a" * 64,
        "usage": {"input_tokens": 1, "output_tokens": 2},
    })
    assert "raw prompt" not in str(record)
    assert "cw_secret-run-id" not in str(record)
    assert record["artifact_sha256"] == "a" * 64


def test_live_outcomes_do_not_count_warning_publication_twice():
    assert _outcome_counts(["published", "published_with_warnings", "quarantined", "rejected_admission"]) == {
        "published": 1, "warning": 1, "quarantined": 1, "rejected": 1,
    }


def test_live_report_cannot_be_done_when_quality_gate_is_not_met():
    assert acceptance_report_status(usage_complete=True, quality_gate_passed=False) == "LOCAL_READY"
    assert acceptance_report_status(usage_complete=True, quality_gate_passed=True) == "DONE"


def test_live_budget_rejects_a_call_before_provider_invocation():
    class FakeGateway:
        def __init__(self):
            self.calls = 0

        def invoke_structured(self, **_kwargs):
            self.calls += 1
            raise AssertionError("provider must not be called after the budget is exhausted")

    gateway = FakeGateway()
    recording = _RecordingGateway(gateway, max_calls=10, max_tokens=10, max_duration_seconds=60)

    with pytest.raises(LiveWorkflowBudgetExceeded):
        recording.invoke_structured(
            messages=[HumanMessage(content="x" * 100)],
            options=SimpleNamespace(max_output_tokens=1),
            context=SimpleNamespace(),
            output_schema=SimpleNamespace(__name__="Payload"),
        )

    assert gateway.calls == 0
    assert recording.budget_exceeded_reason == "token_budget"


def test_scene_budget_preserves_the_quality_review_reserve():
    class FakeGateway:
        def invoke_structured(self, **_kwargs):
            raise AssertionError("budget check must run before the provider")

    budget = LiveWorkflowBudget(
        max_provider_calls=6,
        max_tokens=600,
        max_duration_seconds=60,
        stage_provider_calls={"spec": 1, "scene": 4, "quality_review": 1},
        stage_tokens={"spec": 100, "scene": 400, "quality_review": 100},
    )
    recording = _RecordingGateway(FakeGateway(), budget=budget)
    request = {
        "messages": [HumanMessage(content="x" * 400)],
        "options": SimpleNamespace(max_attempts=1, max_output_tokens=1),
        "context": SimpleNamespace(),
        "output_schema": SimpleNamespace(__name__="CoursewareSceneSpec"),
    }

    with pytest.raises(LiveWorkflowBudgetExceeded):
        recording.invoke_structured(**request)

    assert recording.budget_exceeded_reason == "stage_token_budget:scene"
