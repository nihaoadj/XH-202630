from app.core.courseware.design_system.recipes import SCENE_RECIPE_IDS, resolve_recipe
from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.page_quality import page_quality_issues
from app.core.courseware.renderer import render_courseware
from app.services.courseware.composition import compose_scenes


def _source(resource_id, role, paragraphs, *, exercise_items=None):
    blocks = [
        {"block_id": f"{resource_id}-b{index}", "text": text}
        for index, text in enumerate(paragraphs, 1)
    ]
    return {
        "resource_id": resource_id, "resource_type": role, "role": role,
        "version": 1, "content_hash": f"hash-{resource_id}",
        "content": "\n".join(paragraphs), "topic": "RAG 工程链路",
        "knowledge_points": [f"概念-{resource_id}-1", f"概念-{resource_id}-2"],
        "blocks": blocks, "exercise_items": exercise_items or [],
    }


def _rich_sources():
    dense = [
        "先明确输入、输出与证据边界，避免模型在缺少依据时补写结论。",
        "冻结来源快照后，切分、索引、检索、生成和审核均保留可追溯标识。",
        "出现错误时先检查检索证据，再检查提示约束，最后检查模型输出。",
        "验收必须覆盖正确路径、失败路径、恢复路径以及重复执行的幂等性。",
    ]
    return [
        _source("lecture", "lecture", dense),
        _source("case", "case_study", dense),
        _source("practice", "practice", dense),
        _source("assessment", "assessment", dense, exercise_items=[{
            "question": "故障定位时首先检查什么？", "options": ["检索证据", "页面颜色"],
            "answer": "检索证据", "explanation": "冻结来源明确要求先检查检索证据。",
        }]),
    ]


def test_v3_learning_design_has_page_blueprints_without_padding_pages():
    design = build_learning_design(
        _rich_sources(),
        request_options={"expected_duration_minutes": 30, "interaction_intensity": "medium"},
    )
    assert design.schema_version == "3.0"
    assert design.storyboard.schema_version == "2.0"
    assert 8 <= len(design.storyboard.scenes) <= 10
    assert len({scene.scene_id for scene in design.storyboard.scenes}) == len(design.storyboard.scenes)
    assert all(scene.page_role and scene.layout_recipe_id and scene.key_question for scene in design.storyboard.scenes)
    assert all(2 <= scene.content_budget.max_zones <= 4 for scene in design.storyboard.scenes)
    assert not any(scene.kind == "example" for scene in design.storyboard.scenes)


def test_recipes_resolve_for_all_three_themes():
    assert len(SCENE_RECIPE_IDS) == 13
    for theme in ("editorial", "midnight", "paper"):
        for recipe_id in SCENE_RECIPE_IDS:
            assert resolve_recipe(theme, recipe_id)["recipe_id"] == recipe_id


def test_v3_fallback_and_renderer_use_fixed_stage():
    sources = _rich_sources()
    design = build_learning_design(sources, request_options={"expected_duration_minutes": 30})
    scenes, warnings = compose_scenes(sources, learning_design=design)
    assert not [item for item in warnings if item["code"] in {"EMPTY_PAGE", "SCENE_SKIPPED"}]
    document = {"title": "RAG 工程链路", "scenes": scenes}
    artifact = render_courseware(document).decode("utf-8")
    assert "course-stage" in artifact
    assert "height:100dvh" in artifact
    assert '<header class="course-header"' not in artifact
    assert "recipe-editorial_cover" in artifact
    assert "data-page-role" in artifact


def test_page_quality_gate_reports_empty_thin_and_unplanned_pages():
    document = {"scenes": [{
        "scene_id": "empty", "kind": "explain", "page_role": "concept_explanation",
        "layout_recipe_id": "unknown", "blocks": [], "component_blocks": [],
        "content_budget": {"min_chars": 220, "min_zones": 2},
    }]}
    codes = {item["code"] for item in page_quality_issues(document)}
    assert {"EMPTY_PAGE", "THIN_PAGE", "UNDERFILLED_PAGE", "UNPLANNED_LAYOUT", "MISSING_PAGE_CONCLUSION"} <= codes


def test_long_lecture_is_split_into_source_bound_learning_stages_and_practice_is_interactive():
    lecture_text = [
        f"第 {index} 个讲义块解释阶段概念、证据边界、常见误区和进入下一阶段前的检查条件，确保内容足够形成独立学习页面。"
        for index in range(1, 10)
    ]
    sources = [
        _source("lecture", "lecture", lecture_text),
        _source("practice", "practice", lecture_text[:4]),
    ]
    design = build_learning_design(sources, request_options={"expected_duration_minutes": 30})
    lecture_pages = [scene for scene in design.storyboard.scenes if scene.scene_id.startswith("scene:lecture:")]
    assert len(lecture_pages) >= 2
    assert all(scene.page_role == "concept_explanation" for scene in lecture_pages)
    assert not set(lecture_pages[0].source_block_ids).intersection(lecture_pages[1].source_block_ids)
    scenes, _ = compose_scenes(sources, learning_design=design)
    practice = next(scene for scene in scenes if scene["page_role"] == "practice_workspace")
    step_blocks = [block for block in practice["component_blocks"] if block["component"] in {"steps", "ordered_steps"}]
    assert step_blocks and len(step_blocks[0]["steps"]) >= 2


def test_long_high_intensity_course_is_compacted_before_the_release_scene_ceiling():
    lecture_text = [
        f"stage {index}: " + ("evidence boundary misconception practice conclusion " * 8)
        for index in range(1, 48)
    ]
    design = build_learning_design(
        [_source("lecture", "lecture", lecture_text), _source("practice", "practice", lecture_text[:6])],
        request_options={"expected_duration_minutes": 30, "interaction_intensity": "high"},
    )
    # The design itself is the release input; it must never be generated above
    # the deterministic reviewer limit merely because a source is verbose.
    assert len(design.storyboard.scenes) <= 14
    assert any(item["code"] == "COURSEWARE_SCENE_CAP_APPLIED" for item in design.warnings)
