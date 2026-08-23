"""LLM Agent that writes one renderer-safe, source-scoped scene at a time."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSceneSpec
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions


def compose_courseware_scene(
    llm_gateway: LLMGateway | None,
    run_id: str,
    scene_id: str,
    deterministic_scene: dict[str, Any],
    source: dict[str, Any],
    *, allowance: LLMCallOptions | None = None,
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """Return None for a failed model call so the service can retain its fallback."""
    if not courseware_ai_available(llm_gateway):
        return None, None
    source_blocks = [
        {"block_id": item["block_id"], "text": str(item.get("text") or "")[:1600]}
        for item in source.get("blocks", [])[:12]
    ]
    review_instruction = str(deterministic_scene.get("_review_instruction") or "").strip()
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是互动课件场景编写器。只输出符合 SceneSpec 的 JSON。只可使用给定来源块支持的内容；"
                    "每个 block 必须携带来源。禁止 HTML、CSS、JavaScript、URL、Markdown 链接和任何可执行内容。"
                    "题目、选项、答案和反馈也必须可由来源支持。"
                )),
                HumanMessage(content=json.dumps({
                    "scene_id": scene_id, "required_kind": deterministic_scene["kind"],
                    "fallback_title": deterministic_scene["title"], "source_resource_id": source["resource_id"],
                    "source_blocks": source_blocks,
                    "supported_components": ["callout", "key_point", "steps", "single_choice", "multiple_choice", "recap", "flashcard", "matching", "ordering"],
                    "review_instruction": review_instruction or None,
                }, ensure_ascii=False)),
            ],
            output_schema=CoursewareSceneSpec,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:{scene_id}", node_name="courseware_scene_composer",
                schema_name="CoursewareSceneSpec",
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        spec = result.output
        allowed_blocks = {item["block_id"] for item in source_blocks}
        if spec.kind != deterministic_scene["kind"] or set(spec.source_refs) != {source["resource_id"]}:
            raise ValueError("AI 场景越过既定类型或来源")
        if not set(spec.source_block_ids).issubset(allowed_blocks):
            raise ValueError("AI 场景引用了未冻结来源块")
        values = [spec.title, *(block.text for block in spec.blocks), *spec.steps, *spec.options, spec.feedback]
        if any(re.search(r"<[^>]+>|https?://|javascript:\s*", str(value or ""), flags=re.IGNORECASE) for value in values):
            raise ValueError("AI 场景包含不安全的学习者内容")
        trace_method = getattr(result, "trace_metadata", None)
        trace = trace_method() if callable(trace_method) else {}
        if not trace:
            return spec.to_renderer_scene(), None
        return spec.to_renderer_scene(), {
            "code": "LLM_TRACE",
            "node_name": "courseware_scene_composer",
            "trace": trace,
        }
    except (LLMGatewayError, ValueError) as exc:
        detail = str(exc)
        code = "AI_SCENE_FALLBACK"
        if "未注册" in detail or "component" in detail.lower():
            code = "AI_SCENE_UNKNOWN_COMPONENT"
        elif "来源块" in detail or "source" in detail.lower():
            code = "AI_SCENE_UNKNOWN_SOURCE_BLOCK"
        return None, {"code": code, "message": f"场景 {scene_id} 的 AI 内容不可用，已保留可追溯的确定性版本"}
