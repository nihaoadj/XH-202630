import pytest

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.agents.resource_workflows.interactive_courseware.quality_reviewer_agent import resolve_review_targets


def _scenes():
    return [
        {"scene_id": "scene-1", "component_blocks": [{"block_id": "block-1"}]},
        {"scene_id": "scene-2", "component_blocks": [{"block_id": "block-2"}]},
    ]


def test_review_v2_localizes_scene_block_and_multi_scene_issues_without_widening():
    issues = [
        {"scope": "scene", "scene_id": "scene-2", "instruction": "补充场景二反馈"},
        {"scope": "block", "block_id": "block-1", "instruction": "修正区块一"},
        {"scope": "scenes", "affected_scene_ids": ["scene-2", "scene-unknown"], "instruction": "统一术语"},
    ]
    assert resolve_review_targets(_scenes(), issues) == [
        ("scene-2", "补充场景二反馈；统一术语"),
        ("scene-1", "修正区块一"),
    ]


def test_review_v2_rejects_unlocalized_error_and_unknown_rubric():
    with pytest.raises(ValueError, match="localized error"):
        CoursewareReviewDecision(schema_version="2.0", status="revise", issues=[{
            "severity": "error", "scope": "scene", "instruction": "无法定位",
        }])
    with pytest.raises(ValueError, match="unknown rubric"):
        CoursewareReviewDecision(schema_version="2.0", status="pass", rubric_scores={"invented": 1.0})

