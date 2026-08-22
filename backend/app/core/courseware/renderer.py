"""Render a closed CoursewareDocument into an offline-safe single HTML file."""

from __future__ import annotations

import html
from typing import Any

from app.core.courseware.runtime import ALLOWED_SCENE_KINDS, SCRIPT, STYLE
from app.core.courseware.security import security_policy


def _text(value: Any) -> str:
    return html.escape(str(value or ""), quote=True)


def render_courseware(document: dict[str, Any]) -> bytes:
    """Render only server-validated component JSON; never accept executable markup."""
    title = _text(document.get("title") or "互动课件")
    scenes = document.get("scenes") or []
    if not scenes:
        raise ValueError("课件至少需要一个场景")
    rendered_scenes: list[str] = []
    for index, scene in enumerate(scenes):
        if scene.get("kind") not in ALLOWED_SCENE_KINDS:
            raise ValueError("课件场景类型不受 runtime 支持")
        if not scene.get("source_refs"):
            raise ValueError("每个课件场景必须包含冻结来源引用")
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
                f'<label class="quiz-option"><input type="checkbox" value="{_text(option)}"> {_text(option)}</label>'
                for option in scene.get("options", [])
            )
            answer = "|".join(sorted(str(item) for item in scene.get("answer", [])))
            explanation = _text(scene.get("feedback") or "请再回顾相关内容后重试。")
            interaction = (
                f'<div data-quiz data-answer="{_text(answer)}" data-feedback="{explanation}">'
                f'{options}<p class="feedback" hidden></p></div>'
            )
        rendered_scenes.append(
            f'<section class="scene{" active" if index == 0 else ""}" aria-label="第 {index + 1} 节">'
            f'<h2>{_text(scene.get("title"))}</h2>{blocks}{interaction}</section>'
        )
    html_document = (
        "<!doctype html><html lang=\"zh-CN\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        f'<meta http-equiv="Content-Security-Policy" content="{security_policy()}">'
        f"<title>{title}</title><style>{STYLE}</style></head><body>"
        f'<main class="course"><header class="course-header"><h1>{title}</h1><p>离线互动学习资源</p></header>'
        f'<p class="progress" aria-live="polite"></p>{"".join(rendered_scenes)}'
        '<nav class="nav" aria-label="课件导航"><button type="button" data-nav="-1">上一节</button>'
        '<button type="button" data-nav="1">下一节</button></nav></main>'
        f"<script>{SCRIPT}</script></body></html>"
    )
    return html_document.encode("utf-8")
