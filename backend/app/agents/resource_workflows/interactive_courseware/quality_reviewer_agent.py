"""Advisory LLM Agent for pedagogical quality review."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.models.llm import LLMCallContext


def review_courseware_quality(
    llm_gateway: LLMGateway | None, run_id: str, document: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, str] | None]:
    if not courseware_ai_available(llm_gateway):
        return [], None
    safe_document = {
        "title": document.get("title"),
        "scenes": [
            {"kind": item.get("kind"), "title": item.get("title"), "blocks": item.get("blocks", []),
             "steps": item.get("steps", []), "options": item.get("options", [])}
            for item in document.get("scenes", [])
        ],
    }
    try:
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是课件教学质量审核器。只输出 JSON 审核结论；检查目标连贯性、练习可执行性和测验反馈。"
                    "不要补写事实，不要输出 HTML、链接或代码。只报告需要修改的问题。"
                )),
                HumanMessage(content=json.dumps(safe_document, ensure_ascii=False)),
            ],
            output_schema=CoursewareReviewDecision,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:quality-review", node_name="courseware_quality_reviewer",
                schema_name="CoursewareReviewDecision",
            ),
            options=llm_gateway.options_for("generator", temperature=0.0),
        )
        return [issue.model_dump(mode="json") for issue in result.output.issues], None
    except LLMGatewayError:
        return [], {"code": "AI_QUALITY_REVIEW_SKIPPED", "message": "AI 教学质量审核不可用，已完成规则审核"}
