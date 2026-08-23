"""LLM Agent that designs a source-scoped course outline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSpec
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions
from app.models.courseware.learning_design import CoursewareLearningDesign


def build_courseware_spec(
    llm_gateway: LLMGateway | None, run_id: str, snapshots: list[dict[str, Any]],
    *, allowance: LLMCallOptions | None = None,
    learning_design: CoursewareLearningDesign | None = None,
    request_options: dict[str, Any] | None = None,
) -> tuple[CoursewareSpec | None, dict[str, Any] | None]:
    if not courseware_ai_available(llm_gateway):
        return None, None
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是课程设计器。仅输出课程规格 JSON；不得写学习者正文、不得新增事实、不得输出 HTML、CSS、"
                    "JavaScript、URL。每个场景必须严格填充给定 Storyboard 槽位，引用给定 resource_id，"
                    "source_block_ids 只能来自该资源；如选择视觉设计，只能使用 editorial/midnight/paper 主题、"
                    "固定版式 ID 和 subtle/reduced 动效 ID，不得输出 token 或 CSS。"
                )),
                HumanMessage(content=json.dumps({
                    "sources": [
                        {"resource_id": item["resource_id"], "role": item["role"], "topic": item["topic"],
                         "source_block_ids": [block["block_id"] for block in item.get("blocks", [])]}
                        for item in snapshots
                    ],
                    "storyboard": learning_design.storyboard.model_dump(mode="json") if learning_design else None,
                    "learner_request": request_options or {},
                }, ensure_ascii=False)),
            ],
            output_schema=CoursewareSpec,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:courseware-spec",
                node_name="courseware_spec_builder", schema_name="CoursewareSpec",
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        allowed = {item["resource_id"] for item in snapshots}
        allowed_blocks = {item["resource_id"]: {block["block_id"] for block in item.get("blocks", [])} for item in snapshots}
        if any(scene.source_resource_id not in allowed for scene in result.output.scenes):
            raise ValueError("AI 课程规格引用了未冻结资源")
        if any(not set(scene.source_block_ids).issubset(allowed_blocks[scene.source_resource_id])
               for scene in result.output.scenes):
            raise ValueError("AI 课程规格引用了未冻结来源块")
        trace_method = getattr(result, "trace_metadata", None)
        trace = trace_method() if callable(trace_method) else {}
        if not trace:
            return result.output, None
        return result.output, {
            "code": "LLM_TRACE",
            "node_name": "courseware_spec_builder",
            "trace": trace,
        }
    except (LLMGatewayError, ValueError):
        return None, {"code": "AI_PLAN_FALLBACK", "message": "AI 课程设计不可用，已降级为确定性编排"}
