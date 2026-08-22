"""LLM Agent that designs a source-scoped course outline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSpec
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.models.llm import LLMCallContext


def build_courseware_spec(
    llm_gateway: LLMGateway | None, run_id: str, snapshots: list[dict[str, Any]]
) -> tuple[CoursewareSpec | None, dict[str, str] | None]:
    if not courseware_ai_available(llm_gateway):
        return None, None
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是课程设计器。仅输出课程规格 JSON；不得写学习者正文、不得新增事实、不得输出 HTML、CSS、"
                    "JavaScript、URL。每个场景必须引用给定 resource_id，source_block_ids 只能来自该资源。"
                )),
                HumanMessage(content=json.dumps([
                    {"resource_id": item["resource_id"], "role": item["role"], "topic": item["topic"],
                     "source_block_ids": [block["block_id"] for block in item.get("blocks", [])]}
                    for item in snapshots
                ], ensure_ascii=False)),
            ],
            output_schema=CoursewareSpec,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:courseware-spec",
                node_name="courseware_spec_builder", schema_name="CoursewareSpec",
            ),
            options=llm_gateway.options_for("generator", temperature=0.0),
        )
        allowed = {item["resource_id"] for item in snapshots}
        allowed_blocks = {item["resource_id"]: {block["block_id"] for block in item.get("blocks", [])} for item in snapshots}
        if any(scene.source_resource_id not in allowed for scene in result.output.scenes):
            raise ValueError("AI 课程规格引用了未冻结资源")
        if any(not set(scene.source_block_ids).issubset(allowed_blocks[scene.source_resource_id])
               for scene in result.output.scenes):
            raise ValueError("AI 课程规格引用了未冻结来源块")
        return result.output, None
    except (LLMGatewayError, ValueError):
        return None, {"code": "AI_PLAN_FALLBACK", "message": "AI 课程设计不可用，已降级为确定性编排"}
