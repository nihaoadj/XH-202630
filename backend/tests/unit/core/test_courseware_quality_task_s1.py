import pytest

from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewarePlanEnrichmentV2,
    CoursewareSceneEnrichment,
    CoursewareScenePlan,
    CoursewareSpec,
)
from app.agents.resource_workflows.interactive_courseware.planner_agent import merge_plan_enrichment
from app.config import Settings


def _spec():
    return CoursewareSpec(
        title="平台标题",
        learning_objectives=["目标一", "目标二"],
        scenes=[
            CoursewareScenePlan(source_resource_id="r1", kind="explain", title="场景一", learning_objective="原目标一"),
            CoursewareScenePlan(source_resource_id="r1", kind="practice", title="场景二", learning_objective="原目标二"),
        ],
    )


def test_enrichment_merges_by_stable_ids_not_array_position():
    spec = _spec()
    enrichment = CoursewarePlanEnrichmentV2(
        course_title="模型课程标题",
        course_summary="课程摘要",
        objectives=[],
        scenes=[
            CoursewareSceneEnrichment(scene_id="scene-2", title="第二场景新标题", teaching_intent="迁移练习"),
            CoursewareSceneEnrichment(scene_id="scene-1", title="第一场景新标题", teaching_intent="概念解释"),
        ],
    )
    merged = merge_plan_enrichment(spec, enrichment, scene_ids=["scene-1", "scene-2"])
    assert merged.title == "模型课程标题"
    assert [scene.title for scene in merged.scenes] == ["第一场景新标题", "第二场景新标题"]
    assert [scene.learning_objective for scene in merged.scenes] == ["概念解释", "迁移练习"]


def test_enrichment_unknown_id_is_rejected_as_candidate_not_slot_mismatch():
    with pytest.raises(ValueError, match="未知 scene_id"):
        merge_plan_enrichment(
            _spec(),
            CoursewarePlanEnrichmentV2(
                course_title="标题", course_summary="摘要",
                scenes=[CoursewareSceneEnrichment(scene_id="unknown", title="x", teaching_intent="y")],
            ),
            scene_ids=["scene-1", "scene-2"],
        )


def test_s1_budget_and_retry_limits_are_explicit():
    settings = Settings(_env_file=None)
    assert settings.courseware_total_llm_token_budget == 147456
    assert settings.courseware_planner_token_budget == 16384
    assert settings.courseware_scene_composition_token_budget == 81920
    assert settings.courseware_quality_review_token_budget == 16384
    assert settings.courseware_revision_token_budget == 32768
    assert settings.courseware_auto_revision_max_attempts == 3
    assert settings.llm_max_attempts == 2
