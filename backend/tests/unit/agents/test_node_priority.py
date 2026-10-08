from types import SimpleNamespace

import pytest

from app.agents.shared.retrieval import _queries
from app.agents.resource_workflows.learning_documents.generator_agent import _validate_artifact_scope
from app.agents.resource_workflows.learning_documents.planner_agent import _fallback_plan
from app.core.security.errors import ApplicationError


def test_retrieval_uses_weak_points_only_without_explicit_targets():
    with_targets = SimpleNamespace(
        topic="主题", diagnosis={"weak_points": ["weak-node"]},
        target_skill_nodes=["target-node"],
    )
    queries, _ = _queries(with_targets)
    assert all("weak-node" not in item for item in queries)

    without_targets = SimpleNamespace(
        topic="主题", diagnosis={"weak_points": ["weak-node"]},
        target_skill_nodes=[],
    )
    queries, _ = _queries(without_targets)
    assert any("weak-node" in item for item in queries)


def test_fallback_plan_scopes_actionable_points_to_explicit_targets():
    plan = _fallback_plan({
        "learner": SimpleNamespace(
            weak_points=["weak-node"], strong_points=["strong-node"],
            skill_level="中级",
        ),
        "diagnosis": {"weak_points": ["diagnosis-node"]},
        "topic": "主题",
        "target_skill_nodes": ["target-node"],
    })
    assert [item["topic"] for item in plan["learning_path"]] == ["target-node"]
    assert plan["remedial_points"] == ["target-node"]
    assert "weak-node" not in plan["remedial_points"]


def test_generator_rejects_model_knowledge_points_outside_target_scope():
    artifact = SimpleNamespace(knowledge_points=["target-node", "unexpected-node"])
    spec = SimpleNamespace(knowledge_points=["target-node"])
    with pytest.raises(ApplicationError):
        _validate_artifact_scope(artifact, spec, ["target-node"])
