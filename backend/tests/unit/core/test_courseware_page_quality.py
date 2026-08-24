from app.core.courseware.page_quality import page_quality_issues


def _practice_scene(scene_id: str, source_block_id: str):
    return {
        "scene_id": scene_id, "kind": "practice", "page_role": "practice_workspace",
        "layout_recipe_id": "practice_workspace", "source_block_ids": [source_block_id],
        "lead": "按照本页说明完成当前操作。", "steps": ["完成当前操作"],
        "blocks": ["本步目标与详细操作说明。" * 10], "conclusion": "核对结果后继续。",
        "component_blocks": [{"component": "steps", "text": "本步操作"}],
        "content_budget": {"min_chars": 180, "min_zones": 3},
    }


def test_distinct_source_bound_practice_steps_are_not_false_repetition():
    issues = page_quality_issues({"scenes": [
        _practice_scene("step-1", "b1"), _practice_scene("step-2", "b2"),
    ]})
    assert not any(item["code"] == "REPETITIVE_PAGE" for item in issues)


def test_same_source_bound_duplicate_practice_pages_remain_blocked():
    issues = page_quality_issues({"scenes": [
        _practice_scene("step-1", "b1"), _practice_scene("step-1-copy", "b1"),
    ]})
    assert any(item["code"] == "REPETITIVE_PAGE" for item in issues)
