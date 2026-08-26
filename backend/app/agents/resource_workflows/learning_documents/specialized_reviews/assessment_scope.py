"""Independent, answer-aware semantic scope review for structured assessments."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.llm.gateway import LLMGateway
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.models.shared.agent_contracts import AssessmentScopeReviewV1
from app.models.shared.llm import LLMCallContext


SCOPE_PROMPT = """你是独立的结构化测评范围审核器。逐题审核题干、选项、正确答案、参考答案和 rubric。
每题只能考查其指定能力节点及允许知识点；不得把相邻或更高阶节点内容伪装成允许标签。
只能依据冻结 evidence 判定。每个 question_id 必须恰好输出一次：
- in_scope：题目完全属于当前节点且有指定 evidence 支持；
- out_of_scope：题目涉及其他能力节点或不属于允许知识点；
- insufficient_evidence：当前 evidence 无法支撑题干、答案或 rubric。
in_scope 必须返回恰好一个该题允许的、直接支持题干与答案的 supported_evidence_id；其他结果不得返回不在该题白名单的 evidence。
reason 只写一条不超过 80 字的判定理由，不得复述题干、答案、rubric 或 evidence 原文。只返回严格 JSON。"""


@dataclass(frozen=True)
class AssessmentScopeOutcome:
    passed: bool
    findings: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    revision_instructions: list[dict[str, Any]]
    trace_metadata: dict[str, Any]


def _catalog_nodes() -> dict[str, dict[str, Any]]:
    try:
        rows = load_knowledge_base_manifest().get("skill_nodes", [])
    except Exception:
        rows = []
    return {
        str(row.get("node_id")): row
        for row in rows
        if isinstance(row, dict) and str(row.get("node_id") or "").strip()
    }


def _questions(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for block in payload.get("node_blocks", []):
        for field_name in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions"):
            for question in block.get(field_name, []):
                rows.append({**question, "skill_node_id": block.get("skill_node_id"),
                             "skill_node_name": block.get("skill_node_name")})
    return rows


def review_assessment_scope(
    *,
    resource,
    evidence: list,
    target_skill_nodes: list[str],
    llm_gateway: LLMGateway,
    context: LLMCallContext,
) -> AssessmentScopeOutcome:
    """Review the canonical payload; never use the redacted Markdown projection."""
    payload = resource.assessment_payload
    if not isinstance(payload, dict):
        raise ValueError("structured assessment payload missing")
    questions = _questions(payload)
    if not questions:
        raise ValueError("structured assessment has no questions")
    node_ids = {str(item.get("skill_node_id") or "") for item in questions}
    if not node_ids <= set(target_skill_nodes):
        raise ValueError("assessment node scope does not match frozen targets")
    catalog = _catalog_nodes()
    evidence_by_id = {item.evidence_id: item for item in evidence}
    prompt_questions = []
    expected_ids = set()
    allowed_evidence_by_question: dict[str, set[str]] = {}
    for question in questions:
        question_id = str(question.get("question_id") or "")
        if not question_id or question_id in expected_ids:
            raise ValueError("assessment question ids invalid")
        expected_ids.add(question_id)
        node_id = str(question["skill_node_id"])
        node = catalog.get(node_id, {})
        allowed_evidence = set(question.get("evidence_ids") or [])
        if not allowed_evidence or not allowed_evidence <= set(evidence_by_id):
            raise ValueError("assessment question evidence invalid")
        allowed_evidence_by_question[question_id] = allowed_evidence
        prompt_questions.append({
            "question_id": question_id,
            "skill_node": {"id": node_id, "name": question.get("skill_node_name"),
                           "allowed_knowledge_points": node.get("knowledge_points", [node_id])},
            "knowledge_point_tags": question.get("knowledge_point_tags", []),
            "question_type": question.get("question_type"),
            "difficulty_stage": question.get("difficulty_stage"),
            "stem": question.get("stem"), "options": question.get("options", []),
            "answer_option_ids": question.get("answer_option_ids", []),
            "reference_answer": question.get("reference_answer"), "rubric": question.get("rubric", []),
            "allowed_evidence_ids": sorted(allowed_evidence),
        })
    scoped_evidence = [
        {"evidence_id": item.evidence_id, "excerpt": item.excerpt}
        for item in evidence if item.evidence_id in set().union(*allowed_evidence_by_question.values())
    ]
    result = llm_gateway.invoke_structured(
        messages=[SystemMessage(content=SCOPE_PROMPT), HumanMessage(content=json.dumps({
            "resource_id": resource.resource_id, "questions": prompt_questions,
            "frozen_evidence": scoped_evidence,
        }, ensure_ascii=False))],
        output_schema=AssessmentScopeReviewV1,
        context=context,
        options=llm_gateway.options_for("assessment_scope_reviewer", temperature=0.0),
    )
    findings = [item.model_dump(mode="json") for item in result.output.findings]
    by_id = {item["question_id"]: item for item in findings}
    if set(by_id) != expected_ids or len(by_id) != len(findings):
        raise ValueError("assessment scope findings must cover each question exactly once")
    invalid_evidence = [
        item["question_id"] for item in findings
        if set(item["supported_evidence_ids"]) - allowed_evidence_by_question[item["question_id"]]
        or (item["decision"] == "in_scope" and not item["supported_evidence_ids"])
    ]
    if invalid_evidence:
        raise ValueError("assessment scope finding evidence invalid")
    failed = [item for item in findings if item["decision"] != "in_scope"]
    issues = [{
        "code": "coverage_gap" if item["decision"] == "out_of_scope" else "evidence_gap",
        "severity": "high", "resource_type": "分阶测试题", "resource_id": resource.resource_id,
        "knowledge_point": next(question["skill_node_id"] for question in questions if question["question_id"] == item["question_id"]),
        "description": f"{item['question_id']}：{item['reason']}",
    } for item in failed[:3]]
    instructions = ([{
        "issue_codes": sorted({item["code"] for item in issues}),
        "target_resource_type": "分阶测试题",
        "action": "仅围绕冻结能力节点、允许知识点和题目 evidence 重建越界或证据不足的题目。",
        "priority": 1,
    }] if issues else [])
    return AssessmentScopeOutcome(
        passed=not failed, findings=findings, issues=issues,
        revision_instructions=instructions, trace_metadata=result.trace_metadata(),
    )
