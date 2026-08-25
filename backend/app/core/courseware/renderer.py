"""Render a closed CoursewareDocument into an offline-safe single HTML file."""

from __future__ import annotations

import html
import re
from typing import Any

from app.core.courseware.runtime import ALLOWED_SCENE_KINDS, SCRIPT, STYLE
from app.core.courseware.components import component_definition, is_registered_component, validate_component_payload
from app.core.courseware.security import security_policy
from app.core.courseware.design_system import THEMES, TOKENS, resolve_layout, resolve_motion, resolve_recipe, resolve_theme
from app.models.courseware.design import CoursewareDesign


def _text(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


_FENCED_CODE = re.compile(r"```[^\n]*\n?(.*?)```", flags=re.DOTALL)


def _rich_text(value: Any) -> str:
    """Render frozen Markdown code as readable, inert code rather than prose."""
    source = str(value or "")
    parts: list[str] = []
    cursor = 0
    for match in _FENCED_CODE.finditer(source):
        prose = source[cursor:match.start()].strip()
        if prose:
            parts.append(f'<p class="component-prose">{_text(prose)}</p>')
        code = match.group(1).strip("\n")
        if code:
            parts.append(f'<pre class="source-code" tabindex="0"><code>{_text(code)}</code></pre>')
        cursor = match.end()
    tail = source[cursor:].strip()
    if tail:
        parts.append(f'<p class="component-prose">{_text(tail)}</p>')
    return "".join(parts) or '<p class="component-prose">来源内容为空。</p>'


def _render_component_block(block: dict[str, Any], *, scene_id: str, index: int) -> str:
    """Render only catalog-owned component shapes, never model-supplied markup."""
    definition = component_definition(block.get("component"), str(block.get("schema_version") or "1.0"))
    if definition is None:
        raise ValueError("课件包含未注册互动组件")
    text = _text(block.get("text"))
    rich_text = _rich_text(block.get("text"))
    css = f"block component-{definition.renderer}"
    component_id = _text(block.get("component_id") or block.get("block_id") or f"{definition.name}-{index}")
    attributes = f'class="{css}" data-component-id="{component_id}" data-scene-id="{_text(scene_id)}"'
    if definition.renderer == "key-point":
        return f'<aside {attributes} aria-label="关键点"><div class="component-content">{rich_text}</div></aside>'
    if definition.renderer == "compare":
        return f'<section {attributes} aria-label="对比说明"><div class="component-content">{rich_text}</div></section>'
    if definition.renderer == "recap":
        return f'<section {attributes} aria-label="复盘"><h3>复盘</h3><div class="component-content">{rich_text}</div></section>'
    if definition.renderer == "callout":
        return f'<aside {attributes} role="note" aria-label="提示"><strong>提示</strong><div class="component-content">{rich_text}</div></aside>'
    if definition.name == "flashcard":
        front, back = _text(block.get("front") or text), _text(block.get("back") or text)
        return f'<section {attributes} data-flashcard tabindex="0" role="button" aria-label="翻转卡片"><p class="flash-front">{front}</p><p class="flash-back" hidden>{back}</p><button type="button" data-flashcard-action="review">再复习</button><button type="button" data-flashcard-action="known">已记住</button></section>'
    if definition.name in {"review_recall_card", "review_distinction_card"}:
        cards = []
        for item in block.get("items") or []:
            question_id = _text(item.get("question_id"))
            prompt = _text(item.get("prompt") or item.get("statement"))
            if definition.name == "review_distinction_card":
                answer = f"判断：{'正确' if item.get('truth_value') else '错误'}<br>纠正：{_text(item.get('correction'))}<br>依据：{_text(item.get('explanation'))}"
            else:
                answer = f"参考答案：{_text(item.get('reference_answer'))}<br>解释：{_text(item.get('explanation'))}<br>达标标准：{_text(item.get('pass_criteria'))}"
            cards.append(f'<article class="review-card" data-review-question-id="{question_id}"><h3>{question_id}</h3><p>{prompt}</p><button type="button" data-review-reveal>显示答案</button><div class="review-answer" hidden>{answer}</div><div class="review-rating" hidden role="group" aria-label="自评"><button type="button" data-review-rating="known">会</button><button type="button" data-review-rating="uncertain">模糊</button><button type="button" data-review-rating="not_known">不会</button></div></article>')
        return f'<section {attributes} data-review-practice data-review-kind="{_text(definition.name)}" aria-label="主动回忆练习"><p>{text}</p><div class="review-card-grid">{"".join(cards)}</div></section>'
    if definition.name == "review_example_card":
        item = block.get("item") or {}
        question_id = _text(item.get("question_id"))
        answer = f"正例：{_text(item.get('positive_candidate'))}<br>决定性边界：{_text(item.get('decisive_boundary'))}<br>解释：{_text(item.get('explanation'))}"
        return f'<section {attributes} data-review-practice data-review-kind="review-example" aria-label="正反例辨认"><p>{text}</p><article class="review-card review-example" data-review-question-id="{question_id}"><h3>{question_id}</h3><div class="review-candidates"><p>A. {_text(item.get("candidate_a"))}</p><p>B. {_text(item.get("candidate_b"))}</p></div><button type="button" data-review-reveal>显示答案</button><div class="review-answer" hidden>{answer}</div><div class="review-rating" hidden role="group" aria-label="自评"><button type="button" data-review-rating="known">会</button><button type="button" data-review-rating="uncertain">模糊</button><button type="button" data-review-rating="not_known">不会</button></div></article></section>'
    if definition.name == "review_reflection":
        return f'<aside {attributes} class="{css} review-reflection" role="note"><h3>边界反思</h3><p>{text}</p><p>本节点未生成正反例辨认题：{_text(block.get("reason"))}。请完成上方回忆与辨析后再核对证据边界。</p></aside>'
    if definition.name == "review_overview":
        rows = "".join(f'<li>{_text(item.get("label"))}：{_text(item.get("value"))}</li>' for item in (block.get("items") or []))
        return f'<section {attributes} class="{css} review-overview" aria-label="复习导览"><h3>复习导览</h3><p>{text}</p><ol>{rows}</ol></section>'
    if definition.name == "review_completion":
        rows = "".join(f'<li data-review-node="{_text(item.get("node_id"))}">{_text(item.get("label"))}：完成全部题目自评后，可回到本节点确认完成。</li>' for item in (block.get("items") or []))
        return f'<section {attributes} class="{css} review-completion" aria-label="完成总结"><p>{text}</p><ol>{rows}</ol><p>自评只用于低置信度学习记录，不计入正式测评成绩。</p></section>'
    if definition.name == "matching":
        pairs = block.get("pairs") or []
        left = "".join(f'<button type="button" data-match="left" data-pair-id="{index}" aria-label="选择左项">{_text(pair.get("left"))}</button>' for index, pair in enumerate(pairs))
        right = "".join(f'<button type="button" data-match="right" data-pair-id="{index}" aria-label="选择右项">{_text(pair.get("right"))}</button>' for index, pair in enumerate(pairs))
        return f'<section {attributes} data-matching data-pair-count="{len(pairs)}" aria-label="配对练习"><p>{text}</p><div class="matching-left" aria-label="左侧项目">{left}</div><div class="matching-right" aria-label="右侧项目">{right}</div><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "ordering":
        items = block.get("ordering_items") or []
        controls = "".join(f'<li data-item-id="{_text(item)}"><button type="button" data-order-move="up" aria-label="上移">↑</button><span>{_text(item)}</span><button type="button" data-order-move="down" aria-label="下移">↓</button></li>' for item in items)
        answer = "|".join(_text(item) for item in (block.get("correct_order") or items))
        return f'<section {attributes} data-ordering data-correct-order="{answer}" aria-label="排序练习"><p>{text}</p><ol>{controls}</ol><button type="button" data-order-submit>提交排序</button><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "branching_scenario":
        nodes = block.get("nodes") or []
        rendered_nodes = []
        for node in nodes:
            options = "".join(
                f'<button type="button" data-branch-option data-option-id="{_text(option.get("option_id"))}" data-next-node="{_text(option.get("next_node_id"))}">{_text(option.get("label") or option.get("option_id"))}</button>'
                for option in (node.get("options") or [])
            )
            rendered_nodes.append(
                f'<div data-branch-node="{_text(node.get("node_id"))}" hidden><p>{_text(node.get("label") or node.get("node_id"))}</p>{options}</div>'
            )
        return f'<section {attributes} data-branching data-current-node="{_text(block.get("start_node_id"))}" aria-label="分支情境"><p>{text}</p>{"".join(rendered_nodes)}<p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "categorization":
        categories = "".join(
            f'<button type="button" data-category-id="{_text(item.get("category_id"))}">{_text(item.get("label") or item.get("category_id"))}</button>'
            for item in (block.get("categories") or [])
        )
        items = "".join(
            f'<button type="button" data-category-item data-item-id="{_text(item.get("item_id"))}" data-correct-category="{_text(item.get("correct_category_id"))}">{_text(item.get("label") or item.get("item_id"))}</button>'
            for item in (block.get("items") or [])
        )
        return f'<section {attributes} data-categorization aria-label="分类练习"><p>{text}</p><div class="category-controls" role="group" aria-label="类别">{categories}</div><div class="category-items" role="group" aria-label="待分类项目">{items}</div><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "word_bank_cloze":
        segments = block.get("prompt_segments") or []
        blanks = {str(item.get("blank_id")): item for item in (block.get("blanks") or [])}
        prompt = []
        for index, segment in enumerate(segments):
            prompt.append(f'<span>{_text(segment)}</span>')
            if index < len(blanks):
                blank_id, blank = list(blanks.items())[index]
                prompt.append(f'<button type="button" data-cloze-blank="{_text(blank_id)}" aria-label="填空">______</button>')
        tokens = "".join(
            f'<button type="button" data-cloze-token="{_text(item.get("token_id"))}">{_text(item.get("label") or item.get("token_id"))}</button>'
            for item in (block.get("tokens") or [])
        )
        return f'<section {attributes} data-word-bank-cloze aria-label="词库填空"><p>{"".join(prompt)}</p><div class="cloze-tokens" role="group" aria-label="词库">{tokens}</div><p class="feedback" aria-live="polite" hidden></p></section>'
    if definition.name == "timeline_explorer":
        events = "".join(
            f'<button type="button" data-timeline-event="{_text(item.get("event_id"))}" aria-label="时间线事件 {_text(item.get("sequence"))}">{_text(item.get("label") or item.get("event_id"))}</button>'
            for item in (block.get("events") or [])
        )
        return f'<section {attributes} data-timeline-explorer aria-label="时间线"><p>{text}</p><div class="timeline-events" role="list">{events}</div><p data-timeline-detail aria-live="polite"></p></section>'
    if definition.schema_version == "3.0":
        items = block.get("items") or []
        if definition.name == "comparison_table":
            rows = "".join(
                f'<tr><th scope="row">{_text(item.get("label"))}</th><td>{_text(item.get("value"))}</td></tr>'
                for item in items
            )
            return f'<section {attributes} aria-label="结构化对比"><p>{text}</p><table><tbody>{rows}</tbody></table></section>'
        rows = "".join(
            f'<li><span>{_text(item.get("label"))}</span><strong>{_text(item.get("value"))}</strong></li>'
            for item in items
        )
        return f'<section {attributes} aria-label="{_text(definition.name)}"><p>{text}</p><ol class="visual-items">{rows}</ol></section>'
    if definition.renderer in {"steps", "ordered-steps"}:
        values = block.get("steps") or [block.get("text") or "完成本步骤"]
        tag = "ol" if definition.renderer == "ordered-steps" else "ul"
        items = "".join(f'<li><label><input type="checkbox" id="{component_id}-step-{i}" data-check="{component_id}-step-{i}"><span>{_text(value)}</span></label></li>' for i, value in enumerate(values))
        return f'<section {attributes} aria-label="步骤"><{tag} class="component-steps">{items}</{tag}></section>'
    if definition.name == "single_choice":
        options = block.get("options") or ["是", "否"]
        controls = "".join(f'<label><input type="radio" name="choice-{_text(block.get("block_id") or "1")}" value="{_text(value)}"><span>{_text(value)}</span></label>' for value in options)
        return f'<fieldset {attributes} aria-label="单选题"><legend>{text}</legend>{controls}<button type="button" class="check">提交</button><p class="feedback" aria-live="polite" hidden></p></fieldset>'
    if definition.name == "multiple_choice":
        options = block.get("options") or ["选项 A", "选项 B"]
        controls = "".join(f'<label><input type="checkbox" value="{_text(value)}"><span>{_text(value)}</span></label>' for value in options)
        return f'<fieldset {attributes} aria-label="多选题"><legend>{text}</legend>{controls}<button type="button" class="check">提交</button><p class="feedback" aria-live="polite" hidden></p></fieldset>'
    return f'<section {attributes} aria-label="{_text(definition.name)}"><h3>{text}</h3></section>'


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
        **TOKENS, **colors,
    }.items())
    return STYLE.replace(":root{", f":root{{{variables};", 1)


SCENE_RECIPE_BY_KIND = {
    "intro": "editorial_cover", "explain": "concept_split", "example": "concept_split",
    "compare": "comparison_matrix", "scenario": "case_diagnostic",
    "practice": "practice_workspace", "quiz": "quiz_focus", "recap": "recap_dashboard",
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
        recipe_id = str(scene.get("layout_recipe_id") or scene.get("recipe_id") or SCENE_RECIPE_BY_KIND[scene["kind"]])
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
            blocks = "".join(
                _render_component_block(
                    block,
                    scene_id=str(scene.get("scene_id") or f"scene-{index}"),
                    index=block_index,
                )
                for block_index, block in enumerate(component_blocks)
            )
        else:
            blocks = "".join(f'<p class="block">{_text(block)}</p>' for block in scene.get("blocks", []))
        interaction = ""
        if scene.get("kind") == "practice" and not any(
            block.get("component") in {"steps", "ordered_steps"}
            for block in component_blocks if isinstance(block, dict)
        ):
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
        scene_heading = title if index == 0 and scene.get("page_role") == "cover" else _text(scene.get("title"))
        lead = f'<p class="scene-lead">{_text(scene.get("lead"))}</p>' if scene.get("lead") else ""
        question = f'<p class="scene-question">{_text(scene.get("key_question"))}</p>' if scene.get("key_question") else ""
        conclusion = f'<p class="scene-conclusion">{_text(scene.get("conclusion"))}</p>' if scene.get("conclusion") else ""
        rendered_scenes.append(
            f'<section class="scene recipe-{_text(recipe["recipe_id"])}{active_class}" data-scene-id="{_text(scene.get("scene_id") or f"scene-{index}")}" data-page-role="{_text(scene.get("page_role"))}" data-practice-variant="{_text(scene.get("practice_variant") or "guided")}" data-recipe-id="{_text(recipe["recipe_id"])}" data-decoration-id="{_text(recipe["decoration_id"])}" aria-label="第 {index + 1} 节">'
            f'<header class="scene-header"><span class="scene-kicker">{_text(scene.get("page_role") or scene.get("kind"))}</span><h2>{scene_heading}</h2>{question}{lead}</header>'
            f'<div class="scene-body">{blocks}{interaction}</div>{conclusion}</section>'
        )
    html_document = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f'<meta http-equiv="Content-Security-Policy" content="{security_policy(style_content=style)}">'
        f"<title>{title}</title><style>{style}</style></head><body>"
        f'<main class="course layout-{resolved_design.layout.layout_id}" data-theme="{resolved_design.theme.theme_id}" data-motion="{resolved_design.motion.motion_id}" data-resource-id="{resource_id}" data-release-id="{release_id}"><header class="course-topbar"><h1>{title}</h1><span>INTERACTIVE COURSEWARE</span></header>'
        f'<p class="progress" aria-live="polite"></p><div class="course-stage">{"".join(rendered_scenes)}</div>'
        '<nav class="nav" aria-label="课件导航"><button type="button" data-nav="-1" aria-label="上一节">上一节</button>'
        '<span class="nav-status">← → 键亦可翻页</span><button type="button" data-nav="1" aria-label="下一节">下一节</button></nav></main>'
        f"<script>{SCRIPT}</script></body></html>"
    )
    return html_document.encode("utf-8")
