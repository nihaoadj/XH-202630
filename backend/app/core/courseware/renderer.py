"""Render a closed CoursewareDocument into an offline-safe single HTML file."""

from __future__ import annotations

import html
from typing import Any

from app.core.courseware.runtime import ALLOWED_SCENE_KINDS, SCRIPT, STYLE
from app.core.courseware.components import component_definition, is_registered_component, validate_component_payload
from app.core.courseware.security import security_policy
from app.core.courseware.design_system import THEMES, TOKENS, resolve_layout, resolve_motion, resolve_recipe, resolve_theme
from app.models.courseware.design import CoursewareDesign


def _text(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def _render_component_block(block: dict[str, Any]) -> str:
    """Render only catalog-owned component shapes, never model-supplied markup."""
    definition = component_definition(block.get("component"), str(block.get("schema_version") or "1.0"))
    if definition is None:
        raise ValueError("课件包含未注册互动组件")
    text = _text(block.get("text"))
    css = f"block component-{definition.renderer}"
    if definition.renderer == "key-point":
        return f'<aside class="{css}" aria-label="关键点">{text}</aside>'
    if definition.renderer == "compare":
        return f'<section class="{css}" aria-label="对比说明">{text}</section>'
    if definition.renderer == "recap":
        return f'<section class="{css}" aria-label="复盘"><h3>复盘</h3><p>{text}</p></section>'
    if definition.renderer == "callout":
        return f'<aside class="{css}" role="note" aria-label="提示"><strong>提示</strong><p>{text}</p></aside>'
    if definition.name == "flashcard":
        front, back = _text(block.get("front") or text), _text(block.get("back") or text)
        return f'<section class="{css}" data-flashcard tabindex="0" role="button" aria-label="翻转卡片"><p class="flash-front">{front}</p><p class="flash-back" hidden>{back}</p><button type="button" data-flashcard-action="review">再复习</button><button type="button" data-flashcard-action="known">已记住</button></section>'
    if definition.name == "matching":
        pairs = block.get("pairs") or []
        left = "".join(f'<button type="button" data-match="left" data-pair-id="{index}" aria-label="选择左项">{_text(pair.get("left"))}</button>' for index, pair in enumerate(pairs))
        right = "".join(f'<button type="button" data-match="right" data-pair-id="{index}" aria-label="选择右项">{_text(pair.get("right"))}</button>' for index, pair in enumerate(pairs))
        return f'<section class="{css}" data-matching data-pair-count="{len(pairs)}" aria-label="配对练习"><p>{text}</p><div class="matching-left" aria-label="左侧项目">{left}</div><div class="matching-right" aria-label="右侧项目">{right}</div><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "ordering":
        items = block.get("ordering_items") or []
        controls = "".join(f'<li data-item-id="{_text(item)}"><button type="button" data-order-move="up" aria-label="上移">↑</button><span>{_text(item)}</span><button type="button" data-order-move="down" aria-label="下移">↓</button></li>' for item in items)
        answer = "|".join(_text(item) for item in (block.get("correct_order") or items))
        return f'<section class="{css}" data-ordering data-correct-order="{answer}" aria-label="排序练习"><p>{text}</p><ol>{controls}</ol><button type="button" data-order-submit>提交排序</button><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.renderer in {"steps", "ordered-steps"}:
        values = block.get("steps") or [block.get("text") or "完成本步骤"]
        tag = "ol" if definition.renderer == "ordered-steps" else "ul"
        items = "".join(f'<li><label><input type="checkbox" id="component-step-{i}" data-check="component-step-{i}"><span>{_text(value)}</span></label></li>' for i, value in enumerate(values))
        return f'<section class="{css}" aria-label="步骤"><{tag} class="component-steps">{items}</{tag}></section>'
    if definition.name == "single_choice":
        options = block.get("options") or ["是", "否"]
        controls = "".join(f'<label><input type="radio" name="choice-{_text(block.get("block_id") or "1")}" value="{_text(value)}"><span>{_text(value)}</span></label>' for value in options)
        return f'<fieldset class="{css}" aria-label="单选题"><legend>{text}</legend>{controls}<button type="button" class="check">提交</button><p class="feedback" aria-live="polite" hidden></p></fieldset>'
    if definition.name == "multiple_choice":
        options = block.get("options") or ["选项 A", "选项 B"]
        controls = "".join(f'<label><input type="checkbox" value="{_text(value)}"><span>{_text(value)}</span></label>' for value in options)
        return f'<fieldset class="{css}" aria-label="多选题"><legend>{text}</legend>{controls}<button type="button" class="check">提交</button><p class="feedback" aria-live="polite" hidden></p></fieldset>'
    return f'<section class="{css}" aria-label="{_text(definition.name)}"><h3>{text}</h3></section>'


def _design_for(document: dict[str, Any], design: CoursewareDesign | dict[str, Any] | None) -> CoursewareDesign:
    raw = design if design is not None else document.get("design") or {}
    if isinstance(raw, CoursewareDesign):
        return raw
    raw = raw if isinstance(raw, dict) else {}
    theme_raw = raw.get("theme") or raw.get("theme_id")
    layout_raw = raw.get("layout") or raw.get("layout_id")
    motion_raw = raw.get("motion") or raw.get("motion_id")
    theme_id = theme_raw.get("theme_id") if isinstance(theme_raw, dict) else theme_raw
    layout_id = layout_raw.get("layout_id") if isinstance(layout_raw, dict) else layout_raw
    motion_id = motion_raw.get("motion_id") if isinstance(motion_raw, dict) else motion_raw
    # Historical documents may omit design; explicit unknown IDs are rejected
    # so a model cannot silently escape the registered design system.
    if any(value is not None and value not in {"editorial", "midnight", "paper", "cover", "chapter", "focus", "compare", "steps", "practice", "recap", "progress", "subtle", "reduced"}
           for value in (theme_id, layout_id, motion_id)):
        raise ValueError("课件包含未注册设计系统 ID")
    theme = resolve_theme(theme_id)
    layout = resolve_layout(layout_id)
    motion = resolve_motion(motion_id)
    return CoursewareDesign(theme=theme, layout=layout, motion=motion)


def _design_style(design: CoursewareDesign) -> str:
    colors = THEMES[design.theme.theme_id]
    variables = ";".join(f"--{key.replace('_', '-') }:{value}" for key, value in {
        **TOKENS,
        "surface": colors["surface"], "canvas": colors["canvas"], "ink": colors["ink"],
        "accent": colors["accent"], "border": colors["border"], "focus": colors["focus"],
    }.items())
    return STYLE.replace(":root{", f":root{{{variables};", 1)


SCENE_RECIPE_BY_KIND = {
    "intro": "cover",
    "explain": "concept",
    "practice": "practice",
    "quiz": "quiz",
    "recap": "recap",
}


def render_courseware(document: dict[str, Any], design: CoursewareDesign | dict[str, Any] | None = None) -> bytes:
    """Render only server-validated component JSON; never accept executable markup."""
    title = _text(document.get("title") or "互动课件")
    resolved_design = _design_for(document, design)
    style = _design_style(resolved_design)
    event_context = document.get("event_context") or {}
    resource_id = _text(event_context.get("resource_id") or "unknown-resource")
    release_id = _text(event_context.get("release_id") or "unknown-release")
    scenes = document.get("scenes") or []
    if not scenes:
        raise ValueError("课件至少需要一个场景")
    rendered_scenes: list[str] = []
    for index, scene in enumerate(scenes):
        if scene.get("kind") not in ALLOWED_SCENE_KINDS:
            raise ValueError("课件场景类型不受 runtime 支持")
        recipe_id = str(scene.get("recipe_id") or SCENE_RECIPE_BY_KIND[scene["kind"]])
        recipe = resolve_recipe(resolved_design.theme.theme_id, recipe_id)
        if not scene.get("source_refs"):
            raise ValueError("每个课件场景必须包含冻结来源引用")
        component_blocks = scene.get("component_blocks") or []
        # Legacy scene-level quiz/practice interaction is a thin adapter. Do
        # not duplicate the component payload's form controls in that path.
        if scene.get("kind") == "quiz" and any(block.get("component") in {"single_choice", "multiple_choice"} for block in component_blocks if isinstance(block, dict)):
            component_blocks = []
        if component_blocks:
            if any(not isinstance(block, dict) or not is_registered_component(
                    block.get("component"), str(block.get("schema_version") or "1.0"))
                   for block in component_blocks):
                raise ValueError("课件包含未注册互动组件")
            if any(not validate_component_payload(block["component"], block) for block in component_blocks):
                raise ValueError("课件互动组件字段或来源不完整")
            blocks = "".join(_render_component_block(block) for block in component_blocks)
        else:
            blocks = "".join(f'<p class="block">{_text(block)}</p>' for block in scene.get("blocks", []))
        interaction = ""
        if scene.get("kind") == "practice":
            steps = "".join(
                f'<li><label><input id="step-{index}-{step}" type="checkbox"> {_text(value)}</label></li>'
                for step, value in enumerate(scene.get("steps", []))
            )
            interaction = f'<ol class="steps">{steps}</ol>'
        elif scene.get("kind") == "quiz":
            options = "".join(
                f'<label class="quiz-option"><input type="radio" name="quiz-{index}" value="{_text(option)}"> {_text(option)}</label>'
                for option in scene.get("options", [])
            )
            answer = "|".join(sorted(str(item) for item in scene.get("answer", [])))
            explanation = _text(scene.get("feedback") or "请再回顾相关内容后重试。")
            interaction = (
                f'<div data-quiz data-answer="{_text(answer)}" data-feedback="{explanation}">'
                f'{options}<p class="feedback" aria-live="polite" hidden></p></div>'
            )
        active_class = " active" if index == 0 else ""
        rendered_scenes.append(
            f'<section class="scene recipe-{_text(recipe["recipe_id"])}{active_class}" data-scene-id="{_text(scene.get("scene_id") or f"scene-{index}")}" data-recipe-id="{_text(recipe["recipe_id"])}" data-decoration-id="{_text(recipe["decoration_id"])}" aria-label="第 {index + 1} 节">'
            f'<h2>{_text(scene.get("title"))}</h2>{blocks}{interaction}</section>'
        )
    html_document = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f'<meta http-equiv="Content-Security-Policy" content="{security_policy(style_content=style)}">'
        f"<title>{title}</title><style>{style}</style></head><body>"
        f'<main class="course layout-{resolved_design.layout.layout_id}" data-theme="{resolved_design.theme.theme_id}" data-motion="{resolved_design.motion.motion_id}" data-resource-id="{resource_id}" data-release-id="{release_id}"><header class="course-header"><h1>{title}</h1><p>离线互动学习资源</p></header>'
        f'<p class="progress" aria-live="polite"></p>{"".join(rendered_scenes)}'
        '<nav class="nav" aria-label="课件导航"><button type="button" data-nav="-1">上一节</button>'
        '<button type="button" data-nav="1">下一节</button></nav></main>'
        f"<script>{SCRIPT}</script></body></html>"
    )
    return html_document.encode("utf-8")
