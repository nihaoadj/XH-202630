import json
import uuid

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.agents.resource_workflows.learning_documents.workflow import build_workflow
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.shared.workflow import WorkflowStateSnapshot
from app.services.generation.generation import build_workflow_state


@pytest.fixture(autouse=True)
def _freeze_legacy_claim_strategy(monkeypatch):
    # This historical contract test was written for the legacy Claim policy.
    # Freeze it so the T45 ``neutral_estimate_v1`` default (which requires a
    # submission preflight) does not leak into the field-mapping assertions.
    legacy = Settings(claim_extraction_strategy="legacy_v3", resource_review_strategy="compat")
    monkeypatch.setattr("app.services.generation.generation.get_settings", lambda: legacy)


def _learner() -> LearnerProfile:
    return LearnerProfile(
        learner_id="contract_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        knowledge_base_id="profile-kb",
        learning_goal="掌握主题",
    )


def test_workflow_compiles_with_expected_baseline_channels():
    workflow = build_workflow()
    schema = workflow.get_input_jsonschema()

    assert {
        "schema_version",
        "run_id",
        "learner_id",
        "learner",
        "topic",
        "knowledge_base_id",
        "diagnostic_result_id",
        "target_skill_nodes",
        "resource_types",
        "difficulty_preference",
        "generation_mode",
        "include_review",
        "include_claim_check",
        "max_iterations",
        "claim_max_iterations",
        "assessment_claim_skipped_resource_ids",
        "constraints",
        "trace",
        "errors",
    } <= set(schema["properties"])


def test_generate_request_maps_every_control_field_to_workflow_state():
    req = GenerateRequest(
        learner_id="contract_001",
        topic="  工业视觉  ",
        knowledge_base_id="request-kb",
        diagnostic_result_id="diag-001",
        target_skill_nodes=["node-a", "node-b"],
        resource_types=["讲义"],
        difficulty_preference="中级",
        generation_mode="strict",
        include_review=True,
        include_claim_check=True,
        max_iterations=1,
        claim_max_iterations=1,
        constraints={"must_include_citations": True, "retrieval_top_k": 5},
    )

    state = build_workflow_state(_learner(), req, run_id="run-fixed")

    assert state["schema_version"] == "1.0"
    assert isinstance(state["learner"], LearnerProfile)
    assert state["run_id"] == "run-fixed"
    assert state["learner_id"] == req.learner_id
    assert state["topic"] == "工业视觉"
    assert state["knowledge_base_id"] == "request-kb"
    assert state["diagnostic_result_id"] == "diag-001"
    assert state["target_skill_nodes"] == ["node-a", "node-b"]
    assert state["resource_types"] == ["讲义"]
    assert state["difficulty_preference"] == "中级"
    assert state["generation_mode"] == "strict"
    assert state["include_review"] is True
    assert state["include_claim_check"] is True
    assert state["max_iterations"] == 1
    assert state["claim_max_iterations"] == 1
    assert state["constraints"]["retrieval_top_k"] == 5
    assert state["generation_attempt"] == 1
    assert state["revision_count"] == 0
    assert state["claim_revision_count"] == 0
    assert state["claim_check_status"] == "pending"
    assert state["assessment_claim_skipped_resource_ids"] == []


def test_claim_check_requires_resource_review():
    with pytest.raises(ValidationError, match="include_claim_check requires include_review"):
        GenerateRequest(
            learner_id="contract_001",
            topic="工业视觉",
            include_review=False,
            include_claim_check=True,
        )


def test_claim_check_defaults_to_disabled_and_remains_disabled_for_explicit_drafts():
    reviewed = GenerateRequest(learner_id="contract_001", topic="工业视觉")
    draft = GenerateRequest(learner_id="contract_001", topic="工业视觉", include_review=False)

    assert reviewed.include_claim_check is False
    assert reviewed.max_iterations == 2
    assert reviewed.claim_max_iterations == 1
    assert draft.include_claim_check is False


@pytest.mark.parametrize("explicit", [None, 0, 1, 3])
def test_claim_revision_default_and_explicit_budget_are_frozen(explicit):
    args = {} if explicit is None else {"claim_max_iterations": explicit}
    request = GenerateRequest(learner_id="contract_001", topic="工业视觉", **args)
    expected = 1 if explicit is None else explicit
    assert GenerateRequest.model_validate_json(request.model_dump_json()).claim_max_iterations == expected
    state = build_workflow_state(_learner(), request)
    assert state["claim_max_iterations"] == expected
    assert WorkflowStateSnapshot.model_validate(state).claim_max_iterations == expected


def test_workflow_state_json_round_trip_preserves_schema_version_and_ids():
    state = build_workflow_state(
        _learner(),
        GenerateRequest(learner_id="contract_001", topic="测试"),
    )
    uuid.UUID(state["run_id"])

    snapshot = WorkflowStateSnapshot.model_validate(state)
    restored = WorkflowStateSnapshot.model_validate_json(snapshot.model_dump_json())

    assert restored.schema_version == "1.0"
    assert restored.run_id == snapshot.run_id
    assert restored.learner.learner_id == "contract_001"
    assert json.loads(restored.model_dump_json())["generation_attempt"] == 1


def test_workflow_state_rejects_unknown_contract_version():
    state = build_workflow_state(
        _learner(),
        GenerateRequest(learner_id="contract_001", topic="测试"),
    )
    state["schema_version"] = "2.0"  # type: ignore[typeddict-item]

    with pytest.raises(ValidationError):
        WorkflowStateSnapshot.model_validate(state)
