"""Advisory LLM Agent for pedagogical quality review."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions


def review_courseware_quality_decision(
    llm_gateway: LLMGateway | None, run_id: str, document: dict[str, Any],
    *, allowance: LLMCallOptions | None = None,
) -> tuple[CoursewareReviewDecision, dict[str, Any] | None]:
    if not courseware_ai_available(llm_gateway):
        return _unavailable("AI_QUALITY_REVIEW_UNAVAILABLE", "AI 教学质量审核不可用")
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
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        trace_method = getattr(result, "trace_metadata", None)
        trace = trace_method() if callable(trace_method) else {}
        if hasattr(result.output, "model_copy"):
            output = result.output.model_copy(update={"trace_metadata": trace})
        else:
            output = result.output
        return output, None
    except LLMGatewayError:
        return _unavailable("AI_QUALITY_REVIEW_GATEWAY_ERROR", "AI 教学质量审核调用失败")
    except Exception:
        # Timeouts, empty responses and schema failures are unavailable review
        # evidence; none of them can be represented as an approval.
        return _unavailable("AI_QUALITY_REVIEW_INVALID_OUTPUT", "AI 教学质量审核未返回有效结构化结论")


def _unavailable(code: str, message: str) -> tuple[CoursewareReviewDecision, dict[str, Any]]:
    return (
        CoursewareReviewDecision(decision="unavailable", confidence=0.0),
        {"code": code, "message": message, "fallback_version": "deterministic-v1"},
    )


def review_courseware_quality(
    llm_gateway: LLMGateway | None, run_id: str, document: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Compatibility adapter for callers that only need serializable issues."""
    decision, warning = review_courseware_quality_decision(llm_gateway, run_id, document)
    return [issue.model_dump(mode="json") for issue in decision.issues], warning
