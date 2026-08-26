"""Advisory LLM Agent for pedagogical quality review."""

from __future__ import annotations

import json
from typing import Any, Literal

from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareReviewDecision
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions


class CoursewareReviewIssueV2Draft(BaseModel):
    """Small, unambiguous provider schema before strict durable validation."""

    model_config = ConfigDict(extra="forbid")

    code: str = Field(default="QUALITY", min_length=1, max_length=64)
    dimension: str | None = Field(default=None, max_length=64)
    severity: Literal["info", "warning", "error"] = "warning"
    scope: Literal["course", "scenes", "scene", "block"] = "course"
    scene_id: str | None = Field(default=None, max_length=96)
    affected_scene_ids: list[str] = Field(default_factory=list, max_length=12)
    instruction: str = Field(min_length=1, max_length=400)
    block_id: str | None = Field(default=None, max_length=96)


class CoursewareReviewDecisionV2Draft(BaseModel):
    """Provider-facing v2-only draft; final release contract stays unchanged."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"
    status: Literal["pass", "revise", "reject", "unavailable"] | None = None
    decision: Literal["approved", "revision_required", "rejected", "unavailable"] | None = None
    issues: list[CoursewareReviewIssueV2Draft] = Field(default_factory=list, max_length=12)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rubric_scores: dict[str, float] = Field(default_factory=dict)
    summary: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_decision(cls, values):
        if isinstance(values, dict) and not values.get("status") and values.get("decision"):
            values = dict(values)
            values["status"] = {"approved": "pass", "revision_required": "revise", "rejected": "reject"}.get(values["decision"], values["decision"])
        return values


_RUBRIC_DIMENSIONS = frozenset({
    "objective_alignment", "coherence", "explanation_depth", "example_usefulness",
    "misconception_handling", "practice_gradient", "feedback_quality",
    "interaction_purpose", "cognitive_load",
})


def normalize_review_draft_for_durable_contract(draft: dict[str, Any]) -> dict[str, Any]:
    """Preserve review findings while removing non-actionable provider ambiguity.

    A missing scene/block locator is not evidence that a pedagogical concern is
    invalid.  It is safely escalated to course scope so the strict durable DTO
    remains valid and the workflow can request a course-level revision. Unknown
    rubric names are provider noise and cannot affect the platform scorecard.
    """

    normalized = dict(draft)
    normalized["rubric_scores"] = {
        str(name): score for name, score in (draft.get("rubric_scores") or {}).items()
        if str(name) in _RUBRIC_DIMENSIONS
    }
    issues: list[dict[str, Any]] = []
    for raw_issue in draft.get("issues") or []:
        issue = dict(raw_issue)
        scope = issue.get("scope")
        has_scene = bool(issue.get("scene_id"))
        has_block = bool(issue.get("block_id"))
        has_scenes = bool(issue.get("affected_scene_ids"))
        if (scope == "block" and not (has_scene and has_block)) or (
            scope == "scene" and not has_scene
        ) or (scope == "scenes" and not has_scenes):
            issue["scope"] = "course"
            issue["scene_id"] = None
            issue["block_id"] = None
            issue["affected_scene_ids"] = []
        issues.append(issue)
    normalized["issues"] = issues
    return normalized


def resolve_review_targets(scenes: list[dict[str, Any]], issues: list[dict[str, Any]]) -> list[tuple[str, str]]:
    """Resolve v2 review issues to valid scene IDs, preserving issue order."""
    # Reviewers see the frozen logical scene_id embedded in scene_json, while
    # retry_scene operates on the durable repository row id. Keep that
    # translation here so field-level issues reach the intended row.
    valid = {str(row.get("scene_id")) for row in scenes}
    logical_to_row = {
        str((row.get("scene_json") or {}).get("scene_id")): str(row.get("scene_id"))
        for row in scenes
        if (row.get("scene_json") or {}).get("scene_id")
    }
    by_block = {
        str(block.get("block_id")): str(row.get("scene_id"))
        for row in scenes
        for block in (row.get("component_blocks") or [])
        if isinstance(block, dict) and block.get("block_id")
    }
    instructions: dict[str, list[str]] = {}
    for issue in issues:
        scope = str(issue.get("scope") or ("block" if issue.get("block_id") else "course"))
        # v1 reviewers only supplied block_id. Preserve that contract while
        # keeping v2 explicit scope semantics for new decisions.
        if scope == "course" and issue.get("block_id"):
            scope = "block"
        targets: list[str] = []
        if scope == "course":
            # A course-wide finding is actionable only when every current
            # scene receives the same bounded repair instruction.  Previously
            # these findings produced no target at all and were immediately
            # quarantined as "unresolved", even though no hard gate failed.
            targets.extend(str(row.get("scene_id")) for row in scenes if row.get("scene_id"))
        elif scope == "block":
            target = by_block.get(str(issue.get("block_id") or ""))
            if target:
                targets.append(target)
        elif scope == "scene":
            target = str(issue.get("scene_id") or "")
            target = logical_to_row.get(target, target)
            if target in valid:
                targets.append(target)
        elif scope == "scenes":
            targets.extend(
                logical_to_row.get(str(target), str(target))
                for target in issue.get("affected_scene_ids") or []
                if logical_to_row.get(str(target), str(target)) in valid
            )
        for target in targets:
            instructions.setdefault(target, []).append(str(issue.get("instruction") or issue.get("code") or "修订教学表达"))
    return [(scene_id, "；".join(values)[:800]) for scene_id, values in instructions.items()]


def review_courseware_quality_decision(
    llm_gateway: LLMGateway | None, run_id: str, document: dict[str, Any],
    *, allowance: LLMCallOptions | None = None,
) -> tuple[CoursewareReviewDecision, dict[str, Any] | None]:
    if not courseware_ai_available(llm_gateway):
        return _unavailable("AI_QUALITY_REVIEW_UNAVAILABLE", "AI 教学质量审核不可用")
    safe_document = {
        "title": document.get("title"),
        "scenes": [
            {"scene_id": item.get("scene_id"), "kind": item.get("kind"), "title": item.get("title"), "blocks": item.get("blocks", []),
             "component_blocks": item.get("component_blocks", []), "steps": item.get("steps", []), "options": item.get("options", [])}
            for item in document.get("scenes", [])
        ],
    }
    # A transient provider failure must not immediately turn a fully valid V2
    # review course into a warning release.  Keep this bounded: the gateway
    # still owns per-call structured repair, while this loop makes at most one
    # fresh review request with the identical frozen document.
    for request_attempt in range(2):
        try:
            result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是课件教学质量审核器。只输出 CoursewareReviewDecision v2 JSON；使用九个 rubric 维度，"
                    "rubric_scores 必须恰好包含 objective_alignment、coherence、explanation_depth、"
                    "example_usefulness、misconception_handling、practice_gradient、feedback_quality、"
                    "interaction_purpose、cognitive_load 九项，每项是 1 到 5 的数字。"
                    "每个问题必须给出 dimension、severity、scope、scene_id 或 block_id 以及可执行 instruction。"
                    "severity 只能是 info、warning 或 error；scope 只能是 course、scenes、scene 或 block。"
                    "依据可见内容评分：不因简洁、没有额外案例或未展示的上下文臆测缺陷；仅在明确违反 rubric 时提出问题。"
                    "status=revise 只能用于有明确、可验证、会影响学习者完成任务的 severity=error 缺陷，"
                    "且每个 error 必须定位到真实 scene_id 或 block_id。不要将改善建议、措辞偏好、"
                    "或无法由当前 JSON 验证的推断写入 issues；这些不构成自动重写理由。"
                    "MISSING_ANSWER 只能用于实际 kind=quiz 且 answer 为空的场景；MISSING_ANSWER_KEY 也同样如此。"
                    "所有关键维度至少为 3、平均至少为 3 且没有明确可修复 error 时返回 status=pass 和空 issues；"
                    "拒绝才返回 status=reject。"
                    "先使用这个最小合法模板，再只替换实际字段："
                    '{"schema_version":"2.0","status":"pass","issues":[],"rubric_scores":{"objective_alignment":4,"coherence":4,"explanation_depth":3,"example_usefulness":3,"misconception_handling":3,"practice_gradient":3,"feedback_quality":4,"interaction_purpose":4,"cognitive_load":3},"confidence":0.9}。'
                    "若发现问题，优先给出有效 scene_id 的 scope=scene；只有能同时提供 scene_id 和 block_id 时才使用 scope=block。"
                    "无法定位但确实影响整体的课程级问题使用 scope=course；它会触发一次有界的全场景修订，"
                    "因此不能用泛泛的改进建议填充 issues。"
                    "不要补写事实，不要输出 HTML、链接或代码。只报告需要修改的问题。"
                )),
                HumanMessage(content=json.dumps(safe_document, ensure_ascii=False)),
            ],
            output_schema=CoursewareReviewDecisionV2Draft,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:quality-review", node_name="courseware_quality_reviewer",
                schema_name="CoursewareReviewDecisionV2Draft",
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
            trace_method = getattr(result, "trace_metadata", None)
            trace = trace_method() if callable(trace_method) else {}
            draft = result.output.model_dump(mode="python") if hasattr(result.output, "model_dump") else result.output
            output = CoursewareReviewDecision.model_validate(
                normalize_review_draft_for_durable_contract(draft)
            ).model_copy(update={"trace_metadata": trace})
            return output, ({"code": "AI_QUALITY_REVIEW_RETRY_SUCCEEDED", "message": "AI 教学质量审核在一次有界重试后成功"} if request_attempt else None)
        except LLMGatewayError:
            if request_attempt == 0:
                continue
            return _unavailable("AI_QUALITY_REVIEW_GATEWAY_ERROR", "AI 教学质量审核调用失败")
        except Exception:
            # Invalid structured output is not safely recoverable by a second
            # identical call; it remains unavailable review evidence.
            return _unavailable("AI_QUALITY_REVIEW_INVALID_OUTPUT", "AI 教学质量审核未返回有效结构化结论")
    return _unavailable("AI_QUALITY_REVIEW_GATEWAY_ERROR", "AI 教学质量审核调用失败")


def _unavailable(code: str, message: str) -> tuple[CoursewareReviewDecision, dict[str, Any]]:
    return (
        CoursewareReviewDecision(schema_version="2.0", status="unavailable", confidence=0.0),
        {"code": code, "message": message, "fallback_version": "deterministic-v1"},
    )


def review_courseware_quality(
    llm_gateway: LLMGateway | None, run_id: str, document: dict[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    """Compatibility adapter for callers that only need serializable issues."""
    decision, warning = review_courseware_quality_decision(llm_gateway, run_id, document)
    return [issue.model_dump(mode="json") for issue in decision.issues], warning
