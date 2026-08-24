"""S0 red tests for the courseware quality task.

These assertions intentionally describe the next quality contract before the
implementation is changed.  They must fail against the pre-S0 baseline.
"""

import json
from pathlib import Path

import pytest

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.core.courseware.components import component_asset_matrix, is_registered_component
from app.core.courseware.live_model import live_model_config_from_file


ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "tests" / "fixtures" / "courseware" / "evals" / "manifest.json"


def test_evaluator_v2_has_twenty_cases_and_quality_dimensions():
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == "2.0"
    assert manifest["budget"]["max_cases"] == 20
    assert len(manifest["cases"]) == 20
    quality_ids = {
        "short-low-interaction",
        "medium-interaction-30m",
        "high-interaction-60m",
        "multi-resource-concept-fusion",
        "duplicate-and-complementary-sources",
        "source-conflict-parallel",
        "constrained-interaction-quota",
        "localized-review-repair",
    }
    assert quality_ids <= {case["id"] for case in manifest["cases"]}
    assert manifest.get("quality_defaults")
    assert all("quality_expectations" in case or manifest.get("quality_defaults") for case in manifest["cases"])


@pytest.mark.parametrize("component", [
    "branching_scenario",
    "categorization",
    "word_bank_cloze",
    "timeline_explorer",
])
def test_v2_components_are_registered(component):
    assert is_registered_component(component, "2.0")
    assert component in component_asset_matrix("2.0")


def test_review_v2_requires_scope_and_rubric():
    decision = CoursewareReviewDecision(
        schema_version="2.0",
        status="revise",
        issues=[{
            "dimension": "coherence",
            "severity": "error",
            "scope": "scene",
            "scene_id": "scene-1",
            "affected_scene_ids": ["scene-1", "scene-2"],
            "instruction": "修复场景衔接",
        }],
        rubric_scores={
            "objective_alignment": 3,
            "coherence": 3,
            "explanation_depth": 3,
            "example_usefulness": 3,
            "misconception_handling": 3,
            "practice_gradient": 3,
            "feedback_quality": 3,
            "interaction_purpose": 3,
            "cognitive_load": 3,
        },
    )
    assert decision.schema_version == "2.0"
    assert decision.status == "revise"


def test_quality_summary_v2_reports_richness_and_quota_metrics():
    from app.core.courseware.quality_summary import build_quality_summary

    summary = build_quality_summary(
        events=[],
        warnings=[],
        required_scene_ids=["scene-1"],
        learning_design={
            "resource_usage_plan": [{"resource_id": "r1", "adopted": True}],
            "storyboard": {"scenes": [{"scene_id": "scene-1", "kind": "intro"}]},
        },
        scenes=[{"scene_id": "scene-1", "kind": "intro", "component_blocks": []}],
    )
    assert summary["schema_version"] == "2.0"
    for field in (
        "publication_success",
        "required_scene_recovery_rate",
        "adopted_source_coverage",
        "cross_source_scene_count",
        "interactive_scene_count",
        "unique_interaction_types",
        "interaction_quota_status",
        "interaction_quota_target",
        "interaction_quota_actual",
        "rubric_scores",
        "rubric_passed",
    ):
        assert field in summary


def test_deepseek_live_config_uses_explicit_current_price_unit_window_and_source():
    config = live_model_config_from_file(
        ROOT / "config" / "courseware_live_model.deepseek.v2.json"
    )

    assert config.price_currency == "USD"
    assert config.price_unit == "USD_per_1M_tokens"
    assert config.pricing_window == "peak"
    assert config.thinking_mode == "disabled"
    assert config.model_version == "DeepSeek-V4-Flash-0731"
    assert config.price_source_url.startswith("https://api-docs.deepseek.com/")
    assert config.input_price_per_1m_tokens_peak == 0.44
    assert config.output_price_per_1m_tokens_peak == 1.32


def test_deepseek_live_config_reserves_stage_budgets_and_a_short_deadline():
    config = live_model_config_from_file(
        ROOT / "config" / "courseware_live_model.deepseek.v2.json"
    )

    assert config.acceptance_budget == {
        "version": "2.0",
        "max_provider_calls": 140,
        "max_total_tokens": 600000,
        "max_duration_seconds": 1200,
        "stages": {
            "spec": {"max_provider_calls": 20, "max_tokens": 80000},
            "scene": {"max_provider_calls": 90, "max_tokens": 400000},
            "quality_review": {"max_provider_calls": 30, "max_tokens": 120000},
        },
    }


def test_deepseek_thinking_mode_is_explicitly_forwarded_to_provider(monkeypatch):
    import app.core.llm.transport as transport_module

    captured = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(transport_module, "ChatOpenAI", FakeChatOpenAI)
    from app.config import Settings

    transport_module.create_chat_model(
        settings=Settings(_env_file=None, llm_thinking_mode="disabled"),
        timeout_seconds=10,
        max_output_tokens=100,
    )

    assert captured["extra_body"] == {"thinking": {"type": "disabled"}}


def test_planner_accepts_pydantic_learning_objectives_in_live_path(monkeypatch):
    from types import SimpleNamespace

    import app.agents.resource_workflows.interactive_courseware.planner_agent as planner
    from app.agents.resource_workflows.interactive_courseware.contracts import (
        CoursewarePlanEnrichmentV2,
        CoursewareScenePlan,
        CoursewareSpec,
    )
    from app.models.courseware.learning_design import (
        CoursewareLearningDesign,
        LearningObjective,
        LearningObjectiveGraph,
        StoryboardScene,
        StoryboardSpec,
    )

    learning_design = CoursewareLearningDesign(
        resource_bundle_hash="bundle-hash",
        learner_context_hash="learner-hash",
        objectives=LearningObjectiveGraph(objectives=(LearningObjective(
            objective_id="objective-1",
            statement="理解核心概念",
            observable_result="能够解释核心概念",
        ),)),
        storyboard=StoryboardSpec(
            objective_graph_hash="objective-graph-hash",
            scenes=(StoryboardScene(scene_id="scene-1", kind="intro"),),
        ),
    )
    output = CoursewareSpec(
        title="课程",
        learning_objectives=["原始目标"],
        scenes=[CoursewareScenePlan(
            source_resource_id="resource-1",
            kind="intro",
            title="场景",
            source_block_ids=["block-1"],
        )],
        enrichment=CoursewarePlanEnrichmentV2(
            course_title="课程",
            course_summary="摘要",
            objectives=[{
                "objective_id": "objective-1",
                "title": "更新目标",
                "teaching_intent": "帮助学习者理解核心概念",
            }],
        ),
    )

    class FakeGateway:
        def invoke_structured(self, **kwargs):
            return SimpleNamespace(output=output)

        def options_for(self, *args, **kwargs):
            return None

    monkeypatch.setattr(planner, "courseware_ai_available", lambda gateway: True)
    result, warning = planner.build_courseware_spec(
        FakeGateway(),
        "run-1",
        [{"resource_id": "resource-1", "role": "text", "topic": "主题", "blocks": [{"block_id": "block-1"}]}],
        learning_design=learning_design,
    )

    assert warning is None
    assert result is not None
    assert result.learning_objectives == ["更新目标"]
