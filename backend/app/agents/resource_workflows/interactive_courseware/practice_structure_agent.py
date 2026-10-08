"""Extract source-bound practice-step structure before planning learner pages."""

from __future__ import annotations

import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewarePracticeStepExtraction
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext, LLMCallOptions


_STEP_HEADING = re.compile(
    r"^\s*#{1,6}\s*(?:第\s*)?(?:步骤\s*)?(\d+|[一二三四五六七八九十]+)\s*(?:[、.．:：)）]|\s+-\s+|\s+)?\s*(.+)?$"
)
_CONTEXT_TAIL_HEADING = re.compile(r"^\s*#{1,6}\s*(?:总结|复盘|检查清单|练习|附录|常见问题)")


def _structure_block_view(block: dict[str, Any]) -> dict[str, str]:
    """Return a compact, non-learner-facing view for the structural model.

    The model decides only immutable block ranges.  Sending entire code fences
    and long prose made the schema response unnecessarily large, which in turn
    caused provider ``finish_reason=length`` failures.  The original blocks are
    retained below for the exact post-model partition validation.
    """
    kind = str(block.get("kind") or "paragraph")
    text = str(block.get("text") or "").strip()
    if kind == "heading":
        preview = text
    elif kind == "code":
        preview = f"代码块（{len(text)} 个字符；与前后步骤标题绑定）"
    else:
        preview = re.sub(r"\s+", " ", text)[:180]
    return {"block_id": str(block["block_id"]), "kind": kind, "preview": preview}


def _step_anchors(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        block for block in blocks
        if str(block.get("kind") or "") == "heading" and _STEP_HEADING.match(str(block.get("text") or ""))
    ]


def _context_boundary_ids(blocks: list[dict[str, Any]], anchors: list[dict[str, Any]]) -> set[str]:
    """Return preamble plus a labelled appendix; neither is an operation."""
    positions = {str(block["block_id"]): index for index, block in enumerate(blocks)}
    first_step = positions[str(anchors[0]["block_id"])]
    context = {str(block["block_id"]) for block in blocks[:first_step]}
    last_step = positions[str(anchors[-1]["block_id"])]
    tail_start = next((
        index for index, block in enumerate(blocks[last_step + 1:], last_step + 1)
        if str(block.get("kind") or "") == "heading" and _CONTEXT_TAIL_HEADING.match(str(block.get("text") or ""))
    ), None)
    if tail_start is not None:
        context.update(str(block["block_id"]) for block in blocks[tail_start:])
    return context


def _validate_anchored_partition(
    extraction: CoursewarePracticeStepExtraction,
    blocks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Require one source-order range per explicit Markdown step heading."""
    anchors = _step_anchors(blocks)
    if not anchors:
        raise ValueError("实操指南缺少可验证的步骤标题锚点")
    anchor_ids = [str(block["block_id"]) for block in anchors]
    steps = [step.model_dump(mode="json") for step in extraction.steps]
    if len(steps) != len(anchor_ids):
        raise ValueError("LLM 提取的步骤数量与文档步骤标题不一致")
    position = {str(block["block_id"]): index for index, block in enumerate(blocks)}
    expected_context = _context_boundary_ids(blocks, anchors)
    expected_ranges = []
    for index, anchor_id in enumerate(anchor_ids):
        start = position[anchor_id]
        end = position[anchor_ids[index + 1]] if index + 1 < len(anchor_ids) else len(blocks)
        expected_ranges.append([
            str(block["block_id"]) for block in blocks[start:end]
            if str(block["block_id"]) not in expected_context
        ])
    if [step["source_block_ids"] for step in steps] != expected_ranges:
        raise ValueError("LLM 步骤没有按标题锚点覆盖连续来源范围")
    context_ids = set(extraction.context_block_ids)
    if context_ids != expected_context:
        raise ValueError("LLM 上下文范围不等于文档前言或标记附录")
    return steps


def extract_practice_step_structure(
    llm_gateway: LLMGateway | None,
    run_id: str,
    source: dict[str, Any],
    *,
    allowance: LLMCallOptions | None = None,
) -> tuple[list[dict[str, Any]] | None, dict[str, Any] | None]:
    """Return validated step groups or ``None`` so the caller uses rule fallback.

    The model receives semantic Markdown blocks and can only return titles plus
    immutable IDs. Explicit ``步骤 N`` headings are hard anchors: one heading
    must produce exactly one continuous source range, preventing prose, code
    or checklist fragments from becoming fake steps.
    """
    if not courseware_ai_available(llm_gateway) or source.get("role") != "practice":
        return None, None
    blocks = [
        {"block_id": str(block["block_id"]), "kind": str(block.get("kind") or "paragraph"), "text": str(block.get("text") or "")}
        for block in source.get("blocks") or []
        if block.get("block_id") and str(block.get("text") or "").strip()
    ]
    anchors = _step_anchors(blocks)
    if not blocks or not anchors:
        return None, {"code": "PRACTICE_STEP_HEADINGS_MISSING", "message": "实操指南缺少可验证的“步骤 N”标题，无法建立逐步骤页面"}
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是实操指南结构分析器。只输出给定 JSON Schema。heading 类型且带“步骤 N”的来源块是不可改变的"
                    "步骤锚点：每个锚点只能对应一个 step，step 数必须等于锚点数。每个 step 必须从自己的锚点开始，"
                    "包含直到下一个步骤锚点前的全部连续来源块（包括段落、代码和列表）；输入中 required_context_block_ids"
                    "列出的前言、总结或附录内容必须且只能放入 context_block_ids。不得把准备、代码、说明、清单或段落单独创建为步骤，不得改写、新增或遗漏来源内容，"
                    "不得输出 HTML、CSS、JavaScript、URL、Markdown 或任何正文。title 仅是该步骤的简短名称。"
                )),
                HumanMessage(content=json.dumps({
                    "source_resource_id": source["resource_id"],
                    "source_blocks": [_structure_block_view(block) for block in blocks],
                    "step_anchor_ids_in_required_order": [item["block_id"] for item in anchors],
                    "required_context_block_ids": sorted(_context_boundary_ids(blocks, anchors)),
                    "response_example": {"steps": [
                        {"title": "准备环境", "source_block_ids": ["block-1", "block-2"]},
                        {"title": "执行验证", "source_block_ids": ["block-3"]},
                    ], "context_block_ids": ["intro-1"]},
                }, ensure_ascii=False)),
            ],
            output_schema=CoursewarePracticeStepExtraction,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:practice-structure:{source['resource_id']}",
                node_name="courseware_practice_structure_extractor",
                schema_name="CoursewarePracticeStepExtraction",
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        steps = _validate_anchored_partition(result.output, blocks)
        trace_method = getattr(result, "trace_metadata", None)
        trace = trace_method() if callable(trace_method) else {}
        return steps, ({"code": "LLM_TRACE", "node_name": "courseware_practice_structure_extractor", "trace": trace} if trace else None)
    except (LLMGatewayError, ValueError) as exc:
        return None, {
            "code": "AI_PRACTICE_STRUCTURE_FALLBACK",
            "message": "实操步骤结构未通过来源覆盖与顺序校验，已使用确定性结构",
            "failure_type": type(exc).__name__,
            # Explicit Markdown headings remain an exact, source-ordered
            # fallback.  Persist it as a recovery event, not a learner-facing
            # warning that suggests the generated guide is unreliable.
            "deterministic_anchor_fallback": True,
        }
