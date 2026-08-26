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


def test_review_completion_summary_counts_renderer_owned_regions():
    issues = page_quality_issues({"scenes": [{
        "scene_id": "scene:review:summary", "kind": "recap", "page_role": "summary_action",
        "layout_recipe_id": "recap_dashboard", "lead": "回顾每个节点的自评，再选择下一步。",
        "blocks": [], "conclusion": "出现不会时返回对应节点。",
        "content_budget": {"min_chars": 140, "min_zones": 3},
        "component_blocks": [{
            "component": "review_completion", "text": "节点完成情况",
            "overall_summary": "本轮复习串联核心概念、判断边界与证据依据；完成自评后，优先回到标记为模糊或不会的题目，重新核对对应来源与前提条件。" * 3,
            "items": [{"node_id": "node-1", "label": "Chunk 切分"}],
        }],
    }]})
    assert not any(item["code"] == "THIN_PAGE" for item in issues)
