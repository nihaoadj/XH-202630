"""Stored membership, rather than client constraints, authorizes round generation."""

import pytest

from app.db.feedback.round_base import RoundConflict
from app.db.feedback.round_memory import MemoryRoundRepository
from app.models.learning_documents.schemas import GenerateRequest, LearnerProfile
from app.services.generation.round_context import load_round_context
from tests.integration.persistence.test_learning_round_repository import (
    NOW, add_member, add_stage, add_stage_member, round_values,
)


@pytest.fixture
def scope():
    repository = MemoryRoundRepository()
    with repository.transaction() as tx:
        tx.insert("learning_rounds", round_values())
        add_member(tx, "a", "primary")
        add_member(tx, "b", "review")
        add_stage(tx)
        add_stage_member(tx, "sa", "a", batch="batch-a")
        add_stage_member(tx, "sb", "b", batch="batch-b")
    learner = LearnerProfile(learner_id="learner", learner_type="test", education="test",
                             major="test", learning_goal="test", knowledge_base_id="kb")
    return repository, learner


def request(node="a", resource="分阶测试题", **changes):
    return GenerateRequest(learner_id="learner", topic="topic", knowledge_base_id="kb",
                           target_skill_nodes=[node], difficulty_preference="初级",
                           resource_types=[resource], **changes)


def test_real_role_and_target_are_loaded_from_persisted_scope(scope):
    repository, learner = scope
    binding = load_round_context(repository, learner, "sb", request("b"))
    assert (binding.role, binding.node_id, binding.batch_id) == ("review", "b", "batch-b")
    with pytest.raises(RoundConflict, match="TARGET_MISMATCH"):
        load_round_context(repository, learner, "sb", request("a", constraints={"role": "primary"}))


def test_review_cannot_expand_resource_types_with_forged_constraints(scope):
    repository, learner = scope
    with pytest.raises(RoundConflict, match="RESOURCE_SCOPE"):
        load_round_context(repository, learner, "sb", request("b", "讲义", constraints={"selection_type": "same_tier"}))


def test_unknown_and_cross_owner_scope_are_rejected(scope):
    repository, learner = scope
    with pytest.raises(RoundConflict, match="NOT_FOUND"):
        load_round_context(repository, learner, "missing", request())
    other = learner.model_copy(update={"learner_id": "other"})
    with pytest.raises(RoundConflict, match="OWNER_MISMATCH"):
        load_round_context(repository, other, "sa", request())


def test_append_cannot_switch_a_source_binding_to_the_review(scope):
    repository, learner = scope
    # A stored binding, not a caller-provided source identity, is required.
    with repository.transaction() as tx:
        tx.insert("learning_round_job_bindings", dict(
            run_id="main-run", stage_node_id="sa", relation_kind="production", created_at=NOW,
        ))
    with pytest.raises(RoundConflict, match="SOURCE_BINDING"):
        load_round_context(repository, learner, "sb", request("b"), relation_kind="append", source_run_id="main-run")
    with pytest.raises(RoundConflict, match="SOURCE_BINDING"):
        load_round_context(repository, learner, "sa", request(), relation_kind="retry", source_run_id="made-up")
