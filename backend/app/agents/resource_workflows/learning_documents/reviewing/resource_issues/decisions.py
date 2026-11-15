"""Derived decision and the controlled public summary projection (T44).

The semantic model never owns the release gate.  The decision is derived from
the validated ledger state alone, and the public summary is a bounded, template
projection that never copies model rationale, answers, rubrics, code or evidence
excerpts.
"""

from __future__ import annotations

from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceReviewOutputV1,
    derived_coverage_rate,
)

from .adapters.base import ResourceMaterial

# Public issue codes are bounded to the same closed set the downstream
# ``revision_instructions_are_valid`` validator accepts.  The internal
# free-form ``code`` never reaches the public summary.
_DIMENSION_CODE = {
    "factual_evidence": "factual_risk",
    "coverage": "coverage_gap",
    "difficulty": "difficulty_mismatch",
    "self_contained": "structure_quality",
}

_PUBLIC_LABELS = {
    "factual_risk": "资源存在事实或答案依据问题，需按冻结证据修正。",
    "evidence_gap": "资源所需的冻结证据不足或错配，需补充证据或收窄范围。",
    "procedure_error": "资源的操作依赖或顺序需要修正。",
    "difficulty_mismatch": "资源难度与冻结目标不匹配。",
    "coverage_gap": "资源目标范围或知识点覆盖需要修正。",
    "structure_quality": "资源存在重复、矛盾或可判定性问题。",
    "other": "资源可用性需要按冻结约束复核。",
}


def public_code(issue: ResourceIssueV1) -> str:
    if issue.executability == "evidence_insufficient":
        return "evidence_gap"
    return _DIMENSION_CODE.get(issue.dimension, "other")


def derive_decision(
    *,
    open_issues: tuple[ResourceIssueV1, ...],
    dimensions_pass: bool,
    coverage_rate: float,
    unchanged: bool,
    consecutive_unchanged: int,
    coverage_threshold: float,
    max_consecutive_unchanged: int,
) -> str:
    """The single derived decision for one validated model observation."""
    if not open_issues and dimensions_pass and coverage_rate >= coverage_threshold:
        return "approve"
    if any(item.executability == "evidence_insufficient" for item in open_issues):
        return "human_review"
    if unchanged and consecutive_unchanged >= max_consecutive_unchanged:
        return "human_review"
    return "revise"


def project_public_summary(
    *,
    decision: str,
    output: ResourceReviewOutputV1,
    material: ResourceMaterial,
    resource_id: str | None = None,
    resource_spec_id: str | None = None,
    open_issues: tuple[ResourceIssueV1, ...] = (),
) -> dict:
    """Bounded public projection: at most three issues plus one summary.

    The model's ``reason``/``impact``/``requirement``/``acceptance``/``rationale``
    and any evidence excerpt are never copied here.
    """
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    ordered = sorted(open_issues, key=lambda item: (severity_order[item.severity], item.code))
    issues = []
    for issue in ordered[:3]:
        code = public_code(issue)
        issues.append({
            "code": code,
            "severity": issue.severity,
            "resource_type": material.resource_type,
            "resource_id": resource_id,
            "knowledge_point": None,
            "description": _PUBLIC_LABELS[code],
        })
    raw: dict = {
        "decision": decision,
        "hallucination_score": output.hallucination_score,
        "coverage_rate": derived_coverage_rate(output.targets),
        "difficulty_match": output.dimensions.difficulty == "pass",
        "issues": issues,
        "suggestion": "按冻结证据和逐问题核销结果处理。",
        "revision_instructions": [],
    }
    if decision == "revise":
        raw["revision_instructions"] = [{
            "issue_codes": list(dict.fromkeys(public_code(item) for item in ordered)),
            "target_resource_type": material.resource_type,
            "resource_spec_id": resource_spec_id,
            "action": "按私有问题账本修复全部开放问题，保持冻结目标和证据边界。",
            "priority": 1,
        }]
    return raw
