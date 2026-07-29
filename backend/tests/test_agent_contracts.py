import uuid

import pytest
from pydantic import ValidationError

from app.models.agent_contracts import DiagnosisOutput, NodeResult, build_trace_item, make_error_info
from app.models.schemas import AgentTrace
from app.models.workflow import StepStatus


def test_node_result_requires_explicit_success_and_error_semantics():
    output = DiagnosisOutput(diagnosis={"ability_tags": []})
    success = NodeResult[DiagnosisOutput](status=StepStatus.SUCCESS, output=output)
    assert success.status == StepStatus.SUCCESS

    error = make_error_info("LLM_UPSTREAM_UNAVAILABLE", source="diagnosis")
    degraded = NodeResult[DiagnosisOutput](
        status=StepStatus.DEGRADED,
        output=output,
        error=error,
    )
    assert degraded.error is not None

    with pytest.raises(ValidationError):
        NodeResult[DiagnosisOutput](status=StepStatus.SUCCESS, output=output, error=error)
    with pytest.raises(ValidationError):
        NodeResult[DiagnosisOutput](status=StepStatus.FAILED, output=output, error=error)


def test_agent_trace_status_has_no_default_success():
    with pytest.raises(ValidationError):
        AgentTrace(agent_name="test", action="test", output_summary="test")


def test_trace_ids_are_assigned_before_persistence_and_are_unique():
    state = {"schema_version": "1.0", "run_id": "run-001", "trace": []}
    first = build_trace_item(
        state,
        agent_name="diagnosis",
        action="诊断",
        status=StepStatus.SUCCESS,
        input_summary="safe",
        output_summary="safe",
        decision_reason="safe",
    )
    state["trace"].append(first)
    second = build_trace_item(
        state,
        agent_name="retriever",
        action="检索",
        status=StepStatus.SUCCESS,
        input_summary="safe",
        output_summary="safe",
        decision_reason="safe",
    )

    assert first["run_id"] == second["run_id"] == "run-001"
    assert first["sequence"] == 1
    assert second["sequence"] == 2
    assert first["step_id"] != second["step_id"]
    uuid.UUID(first["step_id"])
    uuid.UUID(second["step_id"])
    AgentTrace.model_validate(first)
    AgentTrace.model_validate(second)
