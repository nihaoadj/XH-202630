import re

from app.core.courseware.design_system.visual_styles import (
    PRACTICE_STYLE_OPTIONS,
    REVIEW_QUESTION_STYLE_MINIMUM,
    STEP_STYLE_SELECTION_COUNT,
    VISUAL_STYLE_METADATA,
    select_practice_step_styles,
    select_practice_visual_style,
    select_review_question_styles,
    visual_style_for_scene,
)
from app.core.courseware.renderer import render_courseware


def _practice_scene_for_family(family: str) -> dict:
    if family == "review":
        return {
            "scene_id": "scene:style:review",
            "kind": "practice",
            "page_role": "review_recall",
            "layout_recipe_id": "review_recall_grid",
            "title": "review style test",
            "blocks": ["样式测试"],
            "source_refs": ["guide"],
            "source_block_ids": ["style-test"],
        }
    variant = "code" if family == "step" else family
    subject = "practice.steps.style-test" if family == "step" else f"{family}-style-test"
    return {
        "scene_id": f"scene:style:{family}",
        "kind": "practice",
        "page_role": "practice_workspace",
        "practice_variant": variant,
        "practice_json_schema_version": "3.0",
        "practice_json_subject": subject,
        "title": f"{family} style test",
        "blocks": ["样式测试"],
        "source_refs": ["guide"],
        "source_block_ids": ["style-test"],
    }


def _seed_for_style(family: str, style_id: str) -> str:
    for index in range(10_000):
        seed = f"style-test-{family}-{index}"
        scene = _practice_scene_for_family(family)
        selected = visual_style_for_scene(scene, seed=seed)
        if selected == style_id:
            return seed
    raise AssertionError(f"无法为 {family}/{style_id} 找到测试种子")


def test_practice_visual_style_registry_covers_practice_and_review_pages():
    assert set(PRACTICE_STYLE_OPTIONS) == {"prepare", "step", "verify", "reflect", "review"}
    assert len(PRACTICE_STYLE_OPTIONS["prepare"]) == 2
    assert len(PRACTICE_STYLE_OPTIONS["step"]) == 8
    assert STEP_STYLE_SELECTION_COUNT == 5
    assert len(PRACTICE_STYLE_OPTIONS["verify"]) == 2
    assert len(PRACTICE_STYLE_OPTIONS["reflect"]) == 2
    assert len(PRACTICE_STYLE_OPTIONS["review"]) == 6
    assert REVIEW_QUESTION_STYLE_MINIMUM == 4
    assert len(select_review_question_styles(seed="review-style-test")) >= REVIEW_QUESTION_STYLE_MINIMUM
    assert set(VISUAL_STYLE_METADATA) == {
        style_id
        for options in PRACTICE_STYLE_OPTIONS.values()
        for style_id in options
    }


def test_practice_visual_style_selection_is_seed_stable_and_distributed():
    for family, options in PRACTICE_STYLE_OPTIONS.items():
        assert visual_style_for_scene(_practice_scene_for_family(family), seed="same") == visual_style_for_scene(
            _practice_scene_for_family(family), seed="same"
        )
        observed = {
            select_practice_visual_style(family=family, seed=f"distribution-{index}")
            for index in range(2_000)
        }
        assert observed == set(options)


def test_step_styles_choose_four_registered_variants_and_alternate_by_step_order():
    scene = _practice_scene_for_family("step")
    selected = select_practice_step_styles(seed="step-rotation-seed")
    assert len(selected) == 5
    assert set(selected).issubset(set(PRACTICE_STYLE_OPTIONS["step"]))
    rendered_sequence = [
        visual_style_for_scene(scene, seed="step-rotation-seed", sequence_index=index)
        for index in range(8)
    ]
    assert tuple(rendered_sequence[:5]) == selected
    assert tuple(rendered_sequence[5:]) == selected[:3]


def test_renderer_rotates_four_selected_step_styles_across_multiple_pages():
    scenes = [
        {
            **_practice_scene_for_family("step"),
            "scene_id": f"scene:style:step:{index}",
            "title": f"步骤 {index + 1}",
        }
        for index in range(8)
    ]
    html = render_courseware(
        {"title": "多步骤样式轮换测试", "visual_style_seed": "renderer-rotation-seed", "scenes": scenes}
    ).decode("utf-8")
    selected = select_practice_step_styles(seed="renderer-rotation-seed")
    rendered = re.findall(r'data-practice-variant="code" data-visual-style="([^"]+)"', html)
    assert rendered == list(selected) + list(selected[:3])


def test_every_registered_style_renders_with_the_same_practice_layout_recipe():
    for family, options in PRACTICE_STYLE_OPTIONS.items():
        scene = _practice_scene_for_family(family)
        for style_id in options:
            seed = _seed_for_style(family, style_id)
            html = render_courseware({"title": "样式测试", "visual_style_seed": seed, "scenes": [scene]}).decode(
                "utf-8"
            )
            assert f'data-visual-style="{style_id}"' in html
            expected_recipe = "review_recall_grid" if family == "review" else "practice_workspace"
            assert f'data-recipe-id="{expected_recipe}"' in html


def test_review_visual_styles_are_seed_stable_but_vary_across_fixed_layout_pages():
    scenes = [
        {
            **_practice_scene_for_family("review"),
            "scene_id": f"scene:style:review:{index}",
            "title": f"复习题 {index + 1}",
        }
        for index in range(12)
    ]
    document = {"title": "复习清单样式轮换测试", "visual_style_seed": "review-sequence-seed", "scenes": scenes}
    first = render_courseware(document).decode("utf-8")
    second = render_courseware(document).decode("utf-8")
    rendered = re.findall(r'data-page-role="review_recall" data-practice-variant="guided" data-visual-style="([^"]+)"', first)
    assert first == second
    assert len(rendered) == len(scenes)
    assert set(rendered).issubset(set(PRACTICE_STYLE_OPTIONS["review"]))
    assert len(set(rendered)) >= 2
    alternate = re.findall(
        r'data-page-role="review_recall" data-practice-variant="guided" data-visual-style="([^"]+)"',
        render_courseware({**document, "visual_style_seed": "review-sequence-seed-alt"}).decode("utf-8"),
    )
    assert alternate != rendered


def test_review_question_pages_always_start_with_four_distinct_styles():
    roles_and_recipes = [
        ("review_recall", "review_recall_grid"),
        ("review_recall", "review_recall_grid"),
        ("review_distinction", "review_distinction_grid"),
        ("review_distinction", "review_distinction_grid"),
        ("review_example", "review_example_focus"),
    ]
    scenes = [
        {
            **_practice_scene_for_family("review"),
            "scene_id": f"scene:style:review-question:{index}",
            "page_role": role,
            "layout_recipe_id": recipe,
        }
        for index, (role, recipe) in enumerate(roles_and_recipes)
    ]
    html = render_courseware(
        {"title": "题目页风格下限测试", "visual_style_seed": "review-question-minimum", "scenes": scenes}
    ).decode("utf-8")
    rendered = re.findall(r'data-page-role="(?:review_recall|review_distinction|review_example)" data-practice-variant="guided" data-visual-style="([^"]+)"', html)
    assert len(rendered) == len(scenes)
    assert len(set(rendered[:REVIEW_QUESTION_STYLE_MINIMUM])) == REVIEW_QUESTION_STYLE_MINIMUM
    assert set(rendered).issubset(set(PRACTICE_STYLE_OPTIONS["review"]))




def _verify_document():
    source_ref = [{"source_resource_id": "guide", "source_block_ids": ["verification"]}]
    return {
        "title": "验证阶段",
        "scenes": [{
            "scene_id": "scene:practice:guide:phase:verify",
            "kind": "practice",
            "page_role": "practice_workspace",
            "practice_variant": "verify",
            "practice_json_schema_version": "3.0",
            "practice_json_subject": "verification",
            "title": "验证阶段",
            "blocks": ["完成检查"],
            "source_refs": ["guide"],
            "source_block_ids": ["verification"],
            "component_blocks": [
                {
                    "schema_version": "1.0",
                    "block_id": "verify-goal",
                    "component": "key_point",
                    "presentation_role": "practice_phase_completion",
                    "label": "验证目标",
                    "text": "检查页面",
                    "source_refs": source_ref,
                },
                {
                    "schema_version": "1.0",
                    "block_id": "verify-items",
                    "component": "steps",
                    "presentation_role": "practice_phase_items",
                    "text": "最终检查项",
                    "steps": ["确认字段映射", "确认页面完整显示"],
                    "source_refs": source_ref,
                },
            ],
        }],
    }


def test_verify_phase_uses_full_height_wrapping_checklist_layout():
    html = render_courseware(_verify_document()).decode("utf-8")

    assert 'data-practice-json-phase="verify"' in html
    assert '.recipe-practice_workspace[data-practice-json-phase="verify"] .scene-body>[data-practice-phase-items]{align-self:stretch!important;height:100%!important' in html
    assert 'background:linear-gradient(135deg,#f7fcff,#e9f7f6)!important' in html
    assert 'overflow-x:hidden!important;overflow-y:auto!important' in html
    assert 'white-space:normal!important;overflow-wrap:anywhere' in html


def test_cover_keeps_two_vertical_lanes_with_horizontal_text_scroll():
    source_ref = [{"source_resource_id": "guide", "source_block_ids": ["cover"]}]
    html = render_courseware({
        "title": "长文本封面测试",
        "resource_name_en": "KNOWLEDGE RETRIEVAL PRACTICE GUIDE",
        "scenes": [{
            "scene_id": "scene:cover",
            "kind": "intro",
            "page_role": "cover",
            "title": "课程导览",
            "source_refs": ["guide"],
            "source_block_ids": ["cover"],
            "component_blocks": [
                {
                    "schema_version": "1.0",
                    "block_id": "learning-scope",
                    "component": "callout",
                    "text": "学习概述：准备阶段、执行步骤、验证阶段与复盘阶段。",
                    "source_refs": source_ref,
                },
                {
                    "schema_version": "1.0",
                    "block_id": "learning-method",
                    "component": "key_point",
                    "text": "学习方法：先阅读目标与说明，再执行代码或操作，随后对照验证结果。",
                    "source_refs": source_ref,
                },
                {
                    "schema_version": "1.0",
                    "block_id": "completion-signal",
                    "component": "key_point",
                    "text": "完成信号：完成全部检查。",
                    "source_refs": source_ref,
                },
            ],
        }],
    }).decode("utf-8")

    assert 'data-cover-learning-scope' in html
    assert 'data-cover-learning-method' in html
    assert '<span class="scene-kicker">KNOWLEDGE RETRIEVAL PRACTICE GUIDE</span>' in html
    assert '<span class="scene-kicker">cover</span>' not in html
    assert '完成信号' not in html
    assert '<strong>提示</strong>' not in html
    assert '.recipe-editorial_cover .scene-body{display:grid!important;grid-template-columns:minmax(0,1fr)!important;grid-template-rows:repeat(2' in html
    assert '.recipe-editorial_cover .scene-header,.recipe-editorial_cover .scene-header .scene-question' in html
    assert 'overflow-x:hidden!important;overflow-y:hidden!important;white-space:normal!important;overflow-wrap:anywhere!important' in html
    assert 'overflow-x:hidden!important;overflow-y:auto!important;white-space:normal!important;overflow-wrap:anywhere!important;max-height:calc(4 * 1.08em)!important' in html
    assert 'overflow-x:auto!important;overflow-y:hidden!important' in html


def test_reflection_goal_titles_share_center_line_and_label_style():
    source_ref = [{"source_resource_id": "guide", "source_block_ids": ["reflection"]}]
    html = render_courseware({
        "title": "复盘与小结",
        "scenes": [{
            "scene_id": "scene:practice:guide:phase:reflect",
            "kind": "practice",
            "page_role": "practice_workspace",
            "practice_variant": "reflect",
            "practice_json_schema_version": "3.0",
            "practice_json_subject": "reflection",
            "title": "复盘与小结",
            "blocks": ["复盘"],
            "source_refs": ["guide"],
            "source_block_ids": ["reflection"],
            "component_blocks": [
                {
                    "schema_version": "1.0",
                    "block_id": "reflection-goal",
                    "component": "key_point",
                    "presentation_role": "practice_reflection_goal",
                    "label": "复盘目标",
                    "text": "梳理本次实操中已验证的流程。",
                    "source_refs": source_ref,
                },
                {
                    "schema_version": "1.0",
                    "block_id": "reflection-summary",
                    "component": "callout",
                    "presentation_role": "practice_reflection_summary",
                    "label": "复盘小结",
                    "text": "回顾输入、结果与验证依据。",
                    "source_refs": source_ref,
                },
            ],
        }],
    }).decode("utf-8")

    assert 'display:flex!important;align-items:center!important;gap:.7rem' in html
    assert '.component-english-label{display:inline-block;margin:0 .05rem 0 0;color:var(--data-2)!important' in html
    assert '>strong{margin:0;color:var(--data-2)!important;font-size:1rem;line-height:1.2' in html


def test_step_code_and_verification_surfaces_are_readable_and_scrollable():
    source_ref = [{"source_resource_id": "guide", "source_block_ids": ["step"]}]
    html = render_courseware({
        "title": "实操步骤",
        "scenes": [{
            "scene_id": "scene:practice:guide:step:1",
            "kind": "practice",
            "page_role": "practice_workspace",
            "practice_variant": "code",
            "practice_json_schema_version": "3.0",
            "practice_json_subject": "practice.steps.step-1",
            "title": "步骤 1｜生成页面",
            "lead": "使用渲染器生成页面。",
            "blocks": ["使用渲染器生成页面。"],
            "source_refs": ["guide"],
            "source_block_ids": ["step"],
            "component_blocks": [
                {
                    "schema_version": "1.0",
                    "block_id": "step-code",
                    "component": "code_block",
                    "text": "生成页面",
                    "language": "python",
                    "code": "render_courseware(document)",
                    "purpose": "生成安全 HTML",
                    "source_refs": source_ref,
                },
                {
                    "schema_version": "1.0",
                    "block_id": "step-verification",
                    "component": "callout",
                    "presentation_role": "practice_verification",
                    "label": "完成验证",
                    "text": "页面显示代码用途、代码内容，并可勾选完成验证。",
                    "source_refs": source_ref,
                },
            ],
        }],
    }).decode("utf-8")

    assert 'overflow-x:auto!important;overflow-y:auto!important;white-space:pre!important' in html
    assert 'font-size:clamp(.95rem,1.25vw,1.2rem)!important;line-height:1.65' in html
    assert 'overflow-x:hidden!important;overflow-y:auto!important;white-space:normal!important;font-size:clamp(1.05rem,1.4vw,1.3rem)' in html
    assert 'text-align:center!important' in html
    assert 'overflow-x:auto!important;overflow-y:hidden!important;white-space:nowrap!important' in html
    assert 'justify-content:center!important;width:max-content;min-width:100%;white-space:nowrap!important' in html
    assert 'text-align:center;white-space:nowrap!important;flex:0 0 auto' in html
    assert 'label strong{font-size:inherit!important;line-height:inherit!important}' in html
