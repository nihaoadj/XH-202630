"""LLM Agent that writes one renderer-safe, source-scoped scene at a time."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewareNarrativeEnrichment, CoursewarePracticeEnrichment, CoursewareSceneSpec,
)
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions


def _format_cover_title(value: str) -> str:
    """Keep the LLM title in the stable learner-facing cover format."""
    title = re.sub(r"^实操指南\s*[|｜:：]\s*", "", str(value or "").strip())
    return f"实操指南 | {title}" if title else "实操指南 | 互动实操指南"


def _strip_learning_overview_label(value: str) -> str:
    return re.sub(r"^学习(?:范围|概述)\s*[：:]\s*", "", str(value or "").strip())


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
    review_page_role = str(deterministic_scene.get("page_role") or "")
    # Review questions and their answers are frozen learning-document output.
    # Only the node's final boundary page may receive a short narrative
    # enrichment; all question pages remain byte-for-byte platform projections.
    if review_page_role.startswith("review_") and review_page_role != "review_example":
        return deepcopy(deterministic_scene), None
    allowed_review_blocks = set(deterministic_scene.get("source_block_ids") or [])
    source_blocks = [
        {"block_id": item["block_id"], "text": str(item.get("text") or "")[:1600]}
        for item in source.get("blocks", [])
        if not allowed_review_blocks or item.get("block_id") in allowed_review_blocks
    ]
    source_blocks = source_blocks[:12]
    review_instruction = str(deterministic_scene.get("_review_instruction") or "").strip()
    scene_kind = str(deterministic_scene["kind"])
    is_step_scene = scene_kind == "practice"
    is_narrative_scene = scene_kind in {"intro", "recap"}
    is_cover_scene = review_page_role == "cover"
    is_platform_enrichment = is_step_scene or is_narrative_scene
    interaction_instruction = (
        "本次是 practice 步骤页：steps 必须是仅含 1 条非空字符串的数组；这条只写当前页的一个可执行动作。"
        "blocks 仍必须是 2 至 4 个对象数组，且每个对象必须包含 component、text、pedagogical_role、source_refs；"
        "不要把步骤写成对象、不要把步骤放进 options、不要省略 conclusion。"
        if is_step_scene else
        "本次不是步骤页：steps 必须是空数组。"
    )
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是互动课件场景编写器。只输出给定 JSON Schema 所要求的字段。只可使用给定来源块支持的内容；"
                    "每个 block 必须携带来源。禁止 HTML、CSS、JavaScript、URL、Markdown 链接和任何可执行内容。"
                    "题目、选项、答案和反馈也必须可由来源支持。首次输出必须完整：每个 block 都要有 block_id、"
                    "component、text、pedagogical_role（仅 explain/example/warning/recap）和非空 source_refs。"
                    "按输入中的页面蓝图填充 2 至 4 个互补信息区，形成引导语、主体信息、证据或示例、页面结论的闭环。"
                    "不得输出只有标题、单句或单卡片的最小占位页。优先使用 callout、key_point、compare、steps、"
                    "single_choice、multiple_choice 或 recap；practice 必须有 steps；"
                    "quiz 必须有至少两个 options、answer（只能取自 options）和 feedback。"
                        + interaction_instruction +
                        ("本次只输出 PracticeEnrichment：title、lead、steps、conclusion；不要输出 blocks、source_refs、options、answer 或 schema_version。"
                       if is_step_scene else "本次只输出 NarrativeEnrichment：title、lead、learning_overview、conclusion；封面 title 必须使用‘实操指南 | 具体实操指南名字’格式；learning_overview 只写概述正文，不要重复‘学习概述：’标签；不要输出 blocks、source_refs、steps、options、answer 或 schema_version。"
                       if is_cover_scene else "本次只输出 NarrativeEnrichment：title、lead、conclusion；不要输出 blocks、source_refs、steps、options、answer 或 schema_version。"
                       if is_narrative_scene else "输出 2.0 合法结构，并用给定来源 ID 替换示例：") +
                    '{"schema_version":"2.0","kind":"explain","title":"标题","lead":"引导语","blocks":[{"schema_version":"1.0",'
                    '"block_id":"block-1","component":"callout","text":"内容","pedagogical_role":"explain",'
                    '"source_refs":[{"source_resource_id":"resource","source_block_ids":["block-1"],"transformation":"paraphrase"}]}],'
                    '"steps":[],"options":[],"answer":[],"conclusion":"页面结论","title_source_refs":[],"feedback_source_refs":[]}。'
                )),
                HumanMessage(content=json.dumps({
                    "scene_id": scene_id, "required_kind": scene_kind,
                    "fallback_title": deterministic_scene["title"], "source_resource_id": source["resource_id"],
                    "source_blocks": source_blocks,
                    "supported_components": ["callout", "key_point", "steps", "single_choice", "multiple_choice", "recap"],
                    "page_blueprint": {
                        key: deterministic_scene.get(key)
                        for key in ("page_role", "layout_recipe_id", "key_question", "required_zones", "content_budget")
                    },
                    "review_instruction": review_instruction or None,
                    "response_contract": (
                        {
                            "schema_version": "2.0", "kind": "practice", "title": "步骤页标题",
                            "lead": "先说明本页要完成什么", "blocks": [
                                {"schema_version": "1.0", "block_id": "zone-1", "component": "callout",
                                 "text": "准备说明", "pedagogical_role": "explain",
                                 "source_refs": [{"source_resource_id": source["resource_id"], "source_block_ids": [source_blocks[0]["block_id"]], "transformation": "adapted_step"}]},
                                {"schema_version": "1.0", "block_id": "zone-2", "component": "steps",
                                 "text": "按以下步骤操作", "pedagogical_role": "example",
                                 "source_refs": [{"source_resource_id": source["resource_id"], "source_block_ids": [source_blocks[0]["block_id"]], "transformation": "adapted_step"}]},
                            ], "steps": ["完成当前页对应的来源操作"], "options": [], "answer": [],
                            "feedback": None, "conclusion": "依据来源完成检查", "title_source_refs": [], "feedback_source_refs": [],
                        } if is_step_scene else
                        {"title": "页面标题", "lead": "本页学习引导", "conclusion": "页面结论"}
                        if is_narrative_scene else None
                    ),
                }, ensure_ascii=False)),
            ],
            output_schema=(CoursewarePracticeEnrichment if is_step_scene else CoursewareNarrativeEnrichment
                           if is_narrative_scene else CoursewareSceneSpec),
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:{scene_id}", node_name="courseware_scene_composer",
                schema_name="CoursewareSceneSpec",
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        spec = result.output
        if is_platform_enrichment:
            # Platform-owned blocks, component IDs and source maps remain
            # immutable. This makes a model retry about instructional prose,
            # not a fragile reconstruction of the renderer contract.
            rendered = deepcopy(deterministic_scene)
            rendered.update({
                "title": _format_cover_title(spec.title) if is_cover_scene else spec.title,
                "lead": spec.lead,
                "conclusion": spec.conclusion,
                "llm_enriched": True,
            })
            if is_cover_scene and getattr(spec, "learning_overview", ""):
                overview = _strip_learning_overview_label(spec.learning_overview)
                rendered["blocks"] = list(rendered.get("blocks") or [])
                if rendered["blocks"]:
                    rendered["blocks"][0] = f"学习概述：{overview}"
                for block in rendered.get("component_blocks") or []:
                    if isinstance(block, dict):
                        block["text"] = f"学习概述：{overview}"
                        break
            if is_step_scene:
                rendered["steps"] = list(spec.steps)
            source_block_ids = list(rendered.get("source_block_ids") or [])
            if is_step_scene and source_block_ids:
                rendered.setdefault("source_map", {})["steps"] = [
                    [source_block_ids[min(index, len(source_block_ids) - 1)]]
                    for index in range(len(spec.steps))
                ]
            if is_step_scene:
                for block in rendered.get("component_blocks") or []:
                    if isinstance(block, dict) and block.get("component") in {"steps", "ordered_steps"}:
                        block["steps"] = list(spec.steps)
            trace_method = getattr(result, "trace_metadata", None)
            trace = trace_method() if callable(trace_method) else {}
            node_name = "courseware_practice_enricher" if is_step_scene else "courseware_narrative_enricher"
            return rendered, ({"code": "LLM_TRACE", "node_name": node_name, "trace": trace} if trace else None)
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
        rendered = spec.to_renderer_scene()
        for key in ("scene_id", "objective_ids", "page_role", "layout_recipe_id", "key_question", "required_zones", "content_budget", "allowed_component_ids"):
            if key in deterministic_scene:
                rendered[key] = deterministic_scene[key]
        if not trace:
            return rendered, None
        return rendered, {
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
