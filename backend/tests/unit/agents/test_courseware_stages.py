"""Stage outcomes cannot bypass source/slot hard gates or recompose recovered scenes."""

import pytest

from app.agents.resource_workflows.interactive_courseware.stages import (
    prepare_design, resolve_scene_candidates, validate_scene_candidates,
)
from app.core.courseware.learning_design import build_learning_design
from app.models.courseware.snapshots import LearnerContextSnapshot


@pytest.mark.parametrize("package,code,status", [
    (None, "COURSEWARE_PRACTICE_JSON_REQUIRED", "rejected_admission"),
    ({"schema_version": "3.0", "practice": {"steps": [{"step_id": "missing"}]}}, "COURSEWARE_PRACTICE_JSON_BINDING_INVALID", "quarantined"),
])
def test_design_failure_is_explicit_without_a_design_artifact(package, code, status):
    result = prepare_design([{"resource_id": "practice", "role": "practice", "practice_guide_payload": package}], LearnerContextSnapshot(), {})
    assert result.design is None and result.warnings == []
    assert result.failure.code == code and result.failure.status == status
    assert result.failure.event_stage == "practice_structure"
    assert result.failure.event_payload == {"error_code": code}


def test_invalid_storyboard_binding_is_a_quarantine_outcome():
    failure = validate_scene_candidates([{"scene_id": "invented", "kind": "explain"}], build_learning_design([]))
    assert failure.code == "COURSEWARE_STORYBOARD_SLOT_MISMATCH"
    assert failure.status == "quarantined" and failure.event_payload["binding_errors"]


@pytest.mark.parametrize("code", ["AI_SCENE_UNKNOWN_COMPONENT", "AI_SCENE_UNKNOWN_SOURCE_BLOCK"])
def test_unknown_ai_contract_keeps_warning_order_and_frozen_bindings(code):
    bases = [{"scene_id": "s1", "objective_ids": ["o1"], "source_refs": ["source"], "source_block_ids": ["b1"]},
             {"scene_id": "s2", "source_refs": ["source"], "source_block_ids": ["b2"]}]
    traces = []
    result = resolve_scene_candidates(
        bases, build_learning_design([]), recovered_scenes=[], ai_enabled=True,
        compose_one=lambda index, scene: (index, {**scene, "source_refs": ["invented"]}, {"code": code} if index == 1 else {"code": "TEMPORARY"}),
        record_trace=lambda index, warning: traces.append(index) or warning,
    )
    assert traces == [0, 1]
    assert [warning["scene_id"] for warning in result.warnings] == ["s1", "s2"]
    assert result.scenes[0]["source_refs"] == ["source"]
    assert result.scenes[0]["objective_ids"] == ["o1"]
    assert result.failure.status == "quarantined" and result.failure.code == code


def test_recovery_never_calls_composer_and_preserves_ai_provenance():
    def unexpected(*args):
        pytest.fail("recovered scenes must not call model composition")

    result = resolve_scene_candidates(
        [{"scene_id": "saved"}], build_learning_design([]),
        recovered_scenes=[{"agent_version": "ai-v1"}], ai_enabled=False,
        compose_one=unexpected, record_trace=lambda index, warning: warning,
    )
    assert result.failure is None and result.ai_enabled is True
    assert result.scenes[0]["scene_id"] == "saved"
    empty = resolve_scene_candidates([], build_learning_design([]), recovered_scenes=[], ai_enabled=False,
                                     compose_one=unexpected, record_trace=unexpected)
    assert empty.scenes == [] and empty.failure is None
