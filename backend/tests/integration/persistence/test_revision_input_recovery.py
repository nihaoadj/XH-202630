"""Checkpoint read-only projection and state-boundary protection for private inputs (T46)."""

from __future__ import annotations

from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.models.reviews.revision_inputs import RESERVED_REVISION_INPUT_KEYS
from app.models.shared.persistence import build_checkpoint_projection, canonical_hash
from app.services.generation.generation import build_workflow_state


def _learner():
    return LearnerProfile(learner_id="learner", learner_type="test", education="本科", major="软件",
                          learning_goal="goal", knowledge_base_id="kb")


def _request(constraints=None):
    return GenerateRequest(learner_id="learner", topic="主题", knowledge_base_id="kb",
                           resource_types=["讲义"], profile_focus_mode="off", include_review=True,
                           include_claim_check=False, constraints=constraints or {})


def test_reserved_keys_are_stripped_at_state_boundary_but_client_extensions_survive():
    constraints = {
        "must_include_citations": True,
        "generation_revision_inputs": {"spec": {"schema_version": "revision-input-v1"}},
        "resource_review_revision": {"issues": []},
        "claim_review_revision": {"problems": []},
        "custom_client_flag": "keep",
    }
    state = build_workflow_state(_learner(), _request(constraints))
    remaining = state["constraints"]
    for reserved in RESERVED_REVISION_INPUT_KEYS:
        assert reserved not in remaining
    assert remaining["custom_client_flag"] == "keep"
    assert remaining["must_include_citations"] is True


def test_generation_revision_inputs_never_enter_checkpoint_projection():
    state = {
        "constraints": {
            "must_include_citations": True,
            "generation_revision_inputs": {"spec": {"schema_version": "revision-input-v1", "kind": "claim", "input": {}}},
            "resource_retry_lineage": {"source_run_id": "source"},
        },
        "diagnosis": {},
        "learning_plan": {},
        "resource_specs": [],
        "resource_executions": [],
        "review_result": {},
        "trace": [],
        "retrieved_evidence": [],
        "generated_resources": [],
    }
    projection = build_checkpoint_projection(state)
    assert "generation_revision_inputs" not in projection
    assert "generation_revision_inputs" not in projection["constraints"]
    assert projection["constraints"]["resource_retry_lineage"] == {"source_run_id": "source"}


def test_adding_private_input_does_not_change_projection_hash():
    base = {
        "run_id": "run",
        "constraints": {"must_include_citations": True},
        "diagnosis": {"summary": "same"},
        "learning_plan": {"goal": "same"},
        "resource_specs": [],
        "resource_executions": [],
        "review_result": {"decision": "approve"},
        "trace": [],
        "retrieved_evidence": [],
        "generated_resources": [],
    }
    with_input = dict(base)
    with_input["constraints"] = {**base["constraints"], "generation_revision_inputs": {"spec": {"kind": "claim"}}}
    assert build_checkpoint_projection(base) == build_checkpoint_projection(with_input)
    assert canonical_hash(build_checkpoint_projection(base)) == canonical_hash(build_checkpoint_projection(with_input))
