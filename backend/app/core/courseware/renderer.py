"""Render a closed CoursewareDocument into an offline-safe single HTML file."""

from __future__ import annotations

import html
import re
from typing import Any

from app.core.courseware.runtime import ALLOWED_SCENE_KINDS, SCRIPT, STYLE
from app.core.courseware.components import component_definition, is_registered_component, validate_component_payload
from app.core.courseware.security import security_policy
from app.core.courseware.design_system import THEMES, TOKENS, resolve_layout, resolve_motion, resolve_recipe, resolve_theme
from app.core.courseware.design_system.visual_styles import (
    REVIEW_QUESTION_PAGE_ROLES,
    practice_style_family,
    visual_style_for_scene,
)
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


def _render_component_block(
    block: dict[str, Any], *, scene_id: str, index: int, scene_page_role: str | None = None
) -> str:
    """Render only catalog-owned component shapes, never model-supplied markup."""
    definition = component_definition(block.get("component"), str(block.get("schema_version") or "1.0"))
    if definition is None:
        raise ValueError("课件包含未注册互动组件")
    text = _text(block.get("text"))
    rich_text = _rich_text(block.get("text"))
    css = f"block component-{definition.renderer}"
    component_id = _text(block.get("component_id") or block.get("block_id") or f"{definition.name}-{index}")
    attributes = f'class="{css}" data-component-id="{component_id}" data-scene-id="{_text(scene_id)}"'
    source_json_path = _text(block.get("source_json_path"))
    evidence_json_path = _text(block.get("evidence_json_path"))
    if source_json_path:
        attributes += f' data-source-json-path="{source_json_path}"'
    if evidence_json_path:
        attributes += f' data-evidence-json-path="{evidence_json_path}"'
    if scene_page_role == "cover" and index == 0:
        attributes += " data-cover-learning-scope"
    elif scene_page_role == "cover" and index == 1:
        attributes += " data-cover-learning-method"
    if definition.renderer == "key-point":
        role = str(block.get("presentation_role") or "")
        label = _text(block.get("label") or "阶段目标")
        if role == "practice_phase_completion":
            english = "VERIFICATION GOAL"
            return (
                f'<section {attributes} data-practice-phase-completion aria-label="{label}">'
                f'<label><input type="checkbox" data-practice-phase-completion-check>'
                f'<span><small class="component-english-label">{english}</small><strong>{label}：</strong>{text}</span></label></section>'
            )
        if role == "practice_phase_goal":
            return (
                f'<section {attributes} data-practice-phase-goal aria-label="{label}">'
                f'<label><input type="checkbox" data-practice-phase-goal-check>'
                f'<span><small class="component-english-label">PHASE GOAL</small><strong>{label}：</strong>{text}</span></label></section>'
            )
        if role == "practice_reflection_goal":
            return f'<aside {attributes} data-practice-reflection-goal aria-label="{label}"><small class="component-english-label">REFLECTION GOAL</small><strong>{label}</strong><div class="component-content">{rich_text}</div></aside>'
        if scene_page_role == "cover" and index == 0:
            return f'<aside {attributes} aria-label="{label}"><strong>{label}</strong><div class="component-content">{rich_text}</div></aside>'
        return f'<aside {attributes} aria-label="关键点"><div class="component-content">{rich_text}</div></aside>'
    if definition.renderer == "compare":
        return f'<section {attributes} aria-label="对比说明"><div class="component-content">{rich_text}</div></section>'
    if definition.renderer == "recap":
        return f'<section {attributes} aria-label="复盘"><h3>复盘</h3><div class="component-content">{rich_text}</div></section>'
    if definition.renderer == "callout":
        label = _text(block.get("label") or "提示")
        if scene_page_role == "cover" and index == 0:
            return f'<aside {attributes} role="note" aria-label="学习范围"><div class="component-content">{rich_text}</div></aside>'
        if block.get("presentation_role") == "practice_verification":
            return (
                f'<section {attributes} data-practice-verification aria-label="{label}">'
                f'<label><input type="checkbox" data-practice-verification-check>'
                f'<span><strong>{label}：</strong>{text}</span></label></section>'
            )
        if block.get("presentation_role") == "practice_reflection_summary":
            return f'<section {attributes} data-practice-reflection-summary aria-label="{label}"><strong>{label}</strong><div class="component-content">{rich_text}</div></section>'
        return f'<aside {attributes} role="note" aria-label="{label}"><strong>{label}</strong><div class="component-content">{rich_text}</div></aside>'
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
            cards.append(f'<article class="review-card" data-review-question-id="{question_id}"><div class="review-question-content"><h3>{question_id}</h3><p>{prompt}</p></div><button type="button" data-review-reveal>显示答案</button><div class="review-answer" hidden>{answer}</div><div class="review-rating" hidden role="group" aria-label="自评"><button type="button" data-review-rating="known" aria-pressed="false">会</button><button type="button" data-review-rating="uncertain" aria-pressed="false">模糊</button><button type="button" data-review-rating="not_known" aria-pressed="false">不会</button></div></article>')
        return f'<section {attributes} data-review-practice data-review-kind="{_text(definition.name)}" aria-label="主动回忆练习"><div class="review-card-grid">{"".join(cards)}</div></section>'
    if definition.name == "review_example_card":
        items = block.get("items") or ([block["item"]] if isinstance(block.get("item"), dict) else [])
        cards = []
        for item in items:
            question_id = _text(item.get("question_id"))
            answer = f"正例：{_text(item.get('positive_candidate'))}<br>决定性边界：{_text(item.get('decisive_boundary'))}<br>解释：{_text(item.get('explanation'))}"
            cards.append(f'<article class="review-card review-example" data-review-question-id="{question_id}"><div class="review-question-content"><h3>{question_id}</h3><div class="review-candidates"><p>A. {_text(item.get("candidate_a"))}</p><p>B. {_text(item.get("candidate_b"))}</p></div></div><button type="button" data-review-reveal>显示答案</button><div class="review-answer" hidden>{answer}</div><div class="review-rating" hidden role="group" aria-label="自评"><button type="button" data-review-rating="known" aria-pressed="false">会</button><button type="button" data-review-rating="uncertain" aria-pressed="false">模糊</button><button type="button" data-review-rating="not_known" aria-pressed="false">不会</button></div></article>')
        return f'<section {attributes} data-review-practice data-review-kind="review-example" aria-label="正反例辨认"><div class="review-card-grid">{"".join(cards)}</div></section>'
    if definition.name == "review_node_summary":
        node_name = _text(block.get("node_name") or "本节点")
        summary_attributes = attributes.replace(f'class="{css}"', f'class="{css} review-node-summary"', 1)
        return f'<aside {summary_attributes} aria-label="{node_name}知识小结"><span class="review-summary-kicker">NODE RECAP</span><h3>{node_name}｜知识小结</h3><div class="review-summary-copy">{rich_text}</div><p class="review-summary-action">带着这份小结回顾刚才的三组练习：能解释概念、辨认边界，并在相似情境中作出判断。</p></aside>'
    if definition.name == "review_reflection":
        reflection_attributes = attributes.replace(f'class="{css}"', f'class="{css} review-reflection"', 1)
        return f'<aside {reflection_attributes} role="note"><h3>边界反思</h3><p>{text}</p><p>本节点未生成正反例辨认题：{_text(block.get("reason"))}。请完成上方回忆与辨析后再核对证据边界。</p></aside>'
    if definition.name == "review_overview":
        overview_attributes = attributes.replace(f'class="{css}"', f'class="{css} review-overview"', 1)
        cards = "".join(f'<article class="review-overview-card"><span>{_text(item.get("label"))}</span><p>{_text(item.get("value"))}</p></article>' for item in (block.get("items") or []))
        rows = "".join(f'<li><strong>{_text(item.get("label"))}</strong><span>{_text(item.get("value"))}</span></li>' for item in (block.get("node_items") or block.get("items") or []))
        return f'<section {overview_attributes} aria-label="复习导览"><div class="review-overview-heading"><span class="review-overview-kicker">START HERE</span><h3>复习导览</h3><p>{text}</p></div><div class="review-overview-grid">{cards}</div><div class="review-overview-path"><span class="review-overview-path-label">复习路径</span><ol>{rows}</ol></div></section>'
    if definition.name == "review_completion":
        rows = "".join(f'<li data-review-node="{_text(item.get("node_id"))}">{_text(item.get("label"))}：完成全部题目自评后，可回到本节点确认完成。</li>' for item in (block.get("items") or []))
        completion_attributes = attributes.replace(f'class="{css}"', f'class="{css} review-completion"', 1)
        overall_summary = _text(block.get("overall_summary") or "本轮复习把核心概念、判断边界与证据依据串联起来；请根据自评结果回到需要再次核对的题目。")
        return f'<section {completion_attributes} aria-label="完成总结"><span class="review-completion-kicker">NEXT STEP</span><h3>完成检查</h3><div class="review-completion-summary"><span>OVERALL REVIEW</span><p>{overall_summary}</p></div><div class="review-completion-next"><span class="review-completion-section-label">节点完成情况</span><ol>{rows}</ol></div><p class="review-completion-note">自评只用于低置信度学习记录，不计入正式测评成绩。</p></section>'
    if definition.name == "code_block":
        language = _text(block.get("language") or "text")
        purpose = _text(block.get("purpose") or text)
        code = _text(block.get("code"))
        return f'<section {attributes} aria-label="代码示例 {language}"><p>{purpose}</p><pre class="source-code"><code data-language="{language}">{code}</code></pre></section>'
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
        phase_attribute = ' data-practice-phase-items' if block.get("presentation_role") == "practice_phase_items" else ""
        phase_english = {"准备项目": "PREPARATION ITEMS", "最终检查项": "VERIFICATION CHECKLIST"}.get(text, "CHECKLIST")
        phase_label = f'<small class="component-english-label">{phase_english}</small><strong class="practice-phase-items-label">{text}</strong>' if phase_attribute else ""
        return f'<section {attributes}{phase_attribute} aria-label="步骤">{phase_label}<{tag} class="component-steps">{items}</{tag}></section>'
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
    resource_name_value = (
        document.get("resource_name_en")
        or event_context.get("resource_name_en")
        or document.get("resource_name")
        or event_context.get("resource_name")
        or document.get("resource_title")
        or (str(document.get("title") or "互动课件").split("｜", 1)[-1])
    )
    resource_name = _text(resource_name_value)
    style_seed = str(
        document.get("visual_style_seed")
        or event_context.get("visual_style_seed")
        or f"{event_context.get('resource_id') or 'unknown-resource'}|{event_context.get('release_id') or 'unknown-release'}"
    )
    scenes = document.get("scenes") or []
    if not scenes:
        raise ValueError("课件至少需要一个场景")
    rendered_scenes: list[str] = []
    step_sequence_index = int(document.get("visual_style_sequence_index") or 0)
    review_question_sequence_index = 0
    for index, scene in enumerate(scenes):
        if scene.get("kind") not in ALLOWED_SCENE_KINDS:
            raise ValueError("课件场景类型不受 runtime 支持")
        recipe_id = str(scene.get("layout_recipe_id") or scene.get("recipe_id") or SCENE_RECIPE_BY_KIND[scene["kind"]])
        recipe = resolve_recipe(resolved_design.theme.theme_id, recipe_id)
        family = practice_style_family(scene)
        is_review_question = family == "review" and str(scene.get("page_role") or "") in REVIEW_QUESTION_PAGE_ROLES
        sequence_index = review_question_sequence_index if is_review_question else step_sequence_index
        visual_style_id = visual_style_for_scene(scene, seed=style_seed, sequence_index=sequence_index)
        if family == "step":
            step_sequence_index += 1
        if is_review_question:
            review_question_sequence_index += 1
        if not scene.get("source_refs"):
            raise ValueError("每个课件场景必须包含冻结来源引用")
        component_blocks = scene.get("component_blocks") or []
        if scene.get("page_role") == "cover":
            # The cover has two vertical information lanes only. The
            # completion signal belongs to later phase pages, not the entry
            # screen.
            component_blocks = component_blocks[:2]
        is_structured_practice_step = (
            scene.get("practice_json_schema_version") == "3.0"
            and str(scene.get("practice_json_subject") or "").startswith("practice.steps.")
        )
        structured_practice_phase = (
            str(scene.get("practice_variant") or "")
            if scene.get("practice_json_schema_version") == "3.0"
            and str(scene.get("practice_variant") or "") in {"prepare", "verify"}
            else ""
        )
        is_structured_practice_reflection = (
            scene.get("practice_json_schema_version") == "3.0"
            and str(scene.get("practice_variant") or "") == "reflect"
        )
        if is_structured_practice_step:
            # The step layout is a direct projection of the fixed V3 guide
            # contract. The instruction is rendered once below the title;
            # only code and completion verification belong in the workspace.
            component_blocks = [
                block for block in component_blocks
                if isinstance(block, dict) and block.get("component") in {"code_block", "callout"}
            ]
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
                    scene_page_role=scene.get("page_role"),
                )
                for block_index, block in enumerate(component_blocks)
            )
        else:
            blocks = "".join(f'<p class="block">{_text(block)}</p>' for block in scene.get("blocks", []))
        interaction = ""
        if scene.get("kind") == "practice" and scene.get("steps") and not any(
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
        scene_heading = (
            _text(scene.get("title"))
            if index == 0 and scene.get("page_role") == "cover" and scene.get("llm_enriched") and scene.get("title")
            else title
            if index == 0 and scene.get("page_role") == "cover"
            else _text(scene.get("title"))
        )
        instruction_block = next(
            (block for block in (scene.get("component_blocks") or [])
             if isinstance(block, dict) and block.get("component") == "key_point"),
            None,
        ) if is_structured_practice_step else None
        title_mapping = _text(scene.get("title_source_json_path"))
        title_attribute = f' data-source-json-path="{title_mapping}"' if title_mapping else ""
        instruction_attributes = ""
        if instruction_block:
            instruction_path = _text(instruction_block.get("source_json_path"))
            evidence_path = _text(instruction_block.get("evidence_json_path"))
            if instruction_path:
                instruction_attributes += f' data-source-json-path="{instruction_path}"'
            if evidence_path:
                instruction_attributes += f' data-evidence-json-path="{evidence_path}"'
        lead = f'<p class="scene-lead"{instruction_attributes}>{_text(scene.get("lead"))}</p>' if scene.get("lead") else ""
        question = f'<p class="scene-question">{_text(scene.get("key_question"))}</p>' if scene.get("key_question") and scene.get("page_role") != "cover" else ""
        conclusion = f'<p class="scene-conclusion">{_text(scene.get("conclusion"))}</p>' if scene.get("conclusion") else ""
        structured_step_attribute = ' data-practice-json-step="true"' if is_structured_practice_step else ''
        structured_phase_attribute = (
            f' data-practice-json-phase="{structured_practice_phase}"'
            if structured_practice_phase else ''
        )
        structured_reflection_attribute = ' data-practice-json-reflection="true"' if is_structured_practice_reflection else ''
        reflection_encouragement = (
            '<p class="practice-reflection-encouragement">每一次认真复盘，都会让下一次实践更从容。</p>'
            if is_structured_practice_reflection else ''
        )
        reflection_kicker = (
            '<span class="practice-reflection-kicker">REFLECTION · WRAP-UP</span>'
            if is_structured_practice_reflection else ''
        )
        phase_kicker = (
            {
                "prepare": "PREPARATION · SETUP",
                "verify": "VERIFICATION · CHECK",
            }.get(str(scene.get("practice_variant") or ""), "PRACTICE · WORKSPACE")
            if structured_practice_phase or is_structured_practice_step else ''
        )
        phase_kicker_markup = (
            f'<span class="practice-phase-kicker">{phase_kicker}</span>'
            if phase_kicker and not is_structured_practice_reflection else ''
        )
        # The practice-guide cover uses a compact, stable English category
        # label.  The generated Chinese title remains the page heading; using
        # the resource name here made the small kicker repeat a long topic.
        scene_kicker = (
            "PRACTICE GUIDE"
            if scene.get("page_role") == "cover" and scene.get("llm_enriched")
            else resource_name
            if scene.get("page_role") == "cover"
            else _text(scene.get("page_role") or scene.get("kind"))
        )
        rendered_scenes.append(
            f'<section class="scene recipe-{_text(recipe["recipe_id"])}{active_class}" data-scene-id="{_text(scene.get("scene_id") or f"scene-{index}")}" data-page-role="{_text(scene.get("page_role"))}" data-practice-variant="{_text(scene.get("practice_variant") or "guided")}" data-visual-style="{_text(visual_style_id or "courseware-default")}"{structured_step_attribute}{structured_phase_attribute}{structured_reflection_attribute} data-recipe-id="{_text(recipe["recipe_id"])}" data-decoration-id="{_text(recipe["decoration_id"])}" aria-label="第 {index + 1} 节">'
            f'<header class="scene-header">{reflection_kicker}{phase_kicker_markup}<span class="scene-kicker">{scene_kicker}</span><h2{title_attribute}>{scene_heading}</h2>{question}{lead}</header>'
            f'<div class="scene-body">{blocks}{interaction}</div>{conclusion}{reflection_encouragement}</section>'
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
