import json
import uuid

import pytest
from pydantic import ValidationError

from app.models.schemas import GenerateRequest, LearnerProfile
from app.models.workflow import WorkflowStateSnapshot
from app.services.generation_service import build_workflow_state


def _learner() -> LearnerProfile:
    return LearnerProfile(
        learner_id="contract_001",
        learner_type="初学者",
        education="本科",
        major="计算机",
        knowledge_base_id="profile-kb",
        learning_goal="掌握主题",
    )


def test_generate_request_maps_every_control_field_to_workflow_state():
    req = GenerateRequest(
        learner_id="contract_001",
        topic="  工业视觉  ",
        knowledge_base_id="request-kb",
        diagnostic_result_id="diag-001",
        target_skill_nodes=["node-a", "node-a", "node-b"],
        resource_types=["讲义", "实操指南"],
        difficulty_preference="中级",
        generation_mode="strict",
        include_review=True,
        include_claim_check=True,
        max_iterations=1,
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
    assert state["resource_types"] == ["讲义", "实操指南"]
    assert state["difficulty_preference"] == "中级"
    assert state["generation_mode"] == "strict"
    assert state["include_review"] is True
    assert state["include_claim_check"] is True
    assert state["max_iterations"] == 1
    assert state["constraints"]["retrieval_top_k"] == 5
    assert state["generation_attempt"] == 1
    assert state["revision_count"] == 0
    assert state["claim_check_status"] == "pending"


def test_claim_check_requires_resource_review():
    with pytest.raises(ValidationError, match="include_claim_check requires include_review"):
        GenerateRequest(
            learner_id="contract_001",
            topic="工业视觉",
            include_review=False,
            include_claim_check=True,
        )


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
