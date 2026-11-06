"""Answer-aware assessment validation; invocation belongs to the public review package."""

from __future__ import annotations

from dataclasses import dataclass
from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.models.reviews.review_audit import ReviewPolicySnapshotV1
from app.models.shared.llm import LLMCallContext
from app.agents.resource_workflows.learning_documents.reviewing import (
    ReviewAuditInput, ReviewCallCollector, build_review_prompt, build_review_request,
    invoke_review, normalize_review_result, resolve_review_profile,
)


_FROZEN_CATALOG: ContextVar[dict | None] = ContextVar("assessment_review_catalog", default=None)


@contextmanager
def assessment_catalog_snapshot(nodes):
    """Inject frozen catalog data for isolated replay without consulting settings."""
    token = _FROZEN_CATALOG.set(deepcopy(nodes))
    try:
        yield
    finally:
        _FROZEN_CATALOG.reset(token)


@dataclass(frozen=True)
class AssessmentScopeOutcome:
    passed: bool
    findings: list[dict[str, Any]]
    issues: list[dict[str, Any]]
    revision_instructions: list[dict[str, Any]]
    trace_metadata: dict[str, Any]
    summary: dict[str, Any]
    llm_result: Any


def _catalog_nodes() -> dict[str, dict[str, Any]]:
    frozen = _FROZEN_CATALOG.get()
    if frozen is not None:
        return deepcopy(frozen)
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

def prepare_assessment_scope(*, resource, evidence, target_skill_nodes):
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
    return ({"resource_id": resource.resource_id, "questions": prompt_questions,
             "frozen_evidence": scoped_evidence}, questions, allowed_evidence_by_question)


def validate_assessment_findings(*, findings, questions, allowed_evidence_by_question, combined):
    expected_ids = {q["question_id"] for q in questions}
    by_id = {item["question_id"]: item for item in findings}
    if set(by_id) != expected_ids or len(by_id) != len(findings):
        raise ValueError("assessment findings must cover each question exactly once")
    normalized = []
    # Always use canonical question order, independently of model output order.
    for question in questions:
        item = by_id[question["question_id"]]
        decision = item["scope_decision"] if combined else item["decision"]
        supported = item["supported_evidence_ids"]
        if (len(supported) > 1 or len(supported) != len(set(supported))
                or set(supported) - allowed_evidence_by_question[question["question_id"]]
                or (decision == "in_scope" and len(supported) != 1)):
            raise ValueError("assessment finding evidence invalid")
        codes = []
        reasons = []
        if decision != "in_scope":
            codes.append("coverage_gap" if decision == "out_of_scope" else "evidence_gap")
            reasons.append("超出冻结节点范围" if decision == "out_of_scope" else "该题证据不足")
        if combined:
            objective = question["question_type"] in {"single_choice", "multiple_choice"}
            if objective != (item["rubric_check"] == "not_applicable"):
                raise ValueError("assessment rubric status incompatible with question type")
            if item["answer_check"] != "pass":
                codes.append("factual_risk" if item["answer_check"] == "fail" else "evidence_gap")
                reasons.append("答案集合错误" if objective else "参考答案依据不足")
            if item["clarity_check"] != "pass":
                codes.append("structure_quality")
                reasons.append("题干或选项无法判定")
            if item["rubric_check"] not in {"pass", "not_applicable"}:
                codes.append("evidence_gap" if item["rubric_check"] == "insufficient_evidence" else "structure_quality")
                reasons.append("评分标准错误或依据不足")
        # Reasons are controlled labels, never excerpts echoed by a model.
        normalized.append({
            "question_id": question["question_id"], "skill_node_id": question["skill_node_id"],
            "scope_decision": decision, "supported_evidence_ids": supported,
            "answer_check": item.get("answer_check"), "clarity_check": item.get("clarity_check"),
            "rubric_check": item.get("rubric_check"), "codes": list(dict.fromkeys(codes)),
            "reason": "；".join(reasons) or "符合冻结审核约束",
        })
    return normalized


def _review_assessment(*, resource, evidence, target_skill_nodes, llm_gateway, context,
                       collector=None, review_id=None, policy=None, combined=False):
    policy = ReviewPolicySnapshotV1.model_validate(policy or {})
    collector = collector if collector is not None else ReviewCallCollector()
    scope_payload, questions, allowed = prepare_assessment_scope(
        resource=resource, evidence=evidence, target_skill_nodes=target_skill_nodes)
    if combined:
        scope_payload = {**scope_payload, "assessment_package": resource.assessment_payload,
                         "target_skill_nodes": list(target_skill_nodes), "difficulty": resource.difficulty}
    phase = "assessment_combined_v2" if combined else "assessment_scope_v1"
    profile = resolve_review_profile(resource_type=resource.resource_type, phase=phase, policy=policy)
    bundle = build_review_prompt(profile=profile)
    request = build_review_request(profile=profile, prompt_bundle=bundle,
        audit_input=ReviewAuditInput(resource=resource, scope_payload=scope_payload, policy=policy))
    result = invoke_review(request=request, llm_gateway=llm_gateway, call_context=context,
                           collector=collector, review_id=review_id)
    try:
        findings = validate_assessment_findings(
            findings=[item.model_dump(mode="json") for item in result.output.findings],
            questions=questions, allowed_evidence_by_question=allowed, combined=combined)
    except ValueError:
        collector.invalid_result(call_id=result.call_id)
        raise
    summary = result.output.summary if combined else {
        "decision": "approve", "hallucination_score": 0.0, "issues": [],
        "difficulty_match": True, "coverage_rate": 0.0 if any(f["codes"] for f in findings) else 1.0,
        "suggestion": "逐题范围审核完成。", "revision_instructions": [],
    }
    try:
        summary = normalize_review_result(output=summary, findings=findings, resource_context=resource)
    except ValueError:
        collector.invalid_result(call_id=result.call_id)
        raise
    return AssessmentScopeOutcome(
        passed=not any(f["codes"] for f in findings), findings=findings,
        issues=summary["issues"], revision_instructions=summary["revision_instructions"],
        trace_metadata=result.trace_metadata(), summary=summary, llm_result=result,
    )


def review_assessment_scope(*, resource, evidence, target_skill_nodes, llm_gateway,
                            context: LLMCallContext, collector=None, review_id=None, policy=None):
    return _review_assessment(resource=resource, evidence=evidence, target_skill_nodes=target_skill_nodes,
        llm_gateway=llm_gateway, context=context, collector=collector, review_id=review_id, policy=policy)


def review_assessment_combined(*, resource, evidence, target_skill_nodes, llm_gateway,
                               context: LLMCallContext, collector=None, review_id=None, policy=None):
    return _review_assessment(resource=resource, evidence=evidence, target_skill_nodes=target_skill_nodes,
        llm_gateway=llm_gateway, context=context, collector=collector, review_id=review_id,
        policy=policy, combined=True)
