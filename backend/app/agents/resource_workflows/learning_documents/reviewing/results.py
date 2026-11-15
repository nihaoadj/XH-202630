"""Adapt bounded summaries while retaining all internal question findings."""

import uuid
import re

from .checks import node_tier_difficulty_review


_ISSUE_LABELS = {
    "factual_risk": "整卷存在事实或答案依据问题。",
    "evidence_gap": "整卷存在冻结证据不足或错配。",
    "procedure_error": "整卷的操作依赖或顺序需要修正。",
    "difficulty_mismatch": "整卷难度与冻结目标不匹配。",
    "coverage_gap": "整卷目标范围或知识点覆盖需要修正。",
    "structure_quality": "整卷存在重复、矛盾或可判定性问题。",
    "other": "整卷可用性需要按冻结约束复核。",
}


def _assessment_summary_projection(*, raw, resource):
    """Public prose is controlled; model echoes cannot disclose private answers."""
    questions = [q["question_id"] for block in resource.assessment_payload["node_blocks"]
                 for field in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions")
                 for q in block[field]]
    nodes = set(resource.knowledge_points)

    def location(text):
        mentioned = set(re.findall(r"\bq-\d{3}\b", text))
        return "、".join([qid for qid in questions if qid in mentioned][:6]) or "整卷"

    normalized = dict(raw)
    normalized["suggestion"] = "整卷审核建议已按问题码与合法题号归一化。"
    normalized["issues"] = []
    for issue in raw.get("issues", []):
        if issue["code"] not in _ISSUE_LABELS or issue.get("claim_ids"):
            raise ValueError("assessment summary issue invalid")
        normalized["issues"].append({**issue, "resource_type": resource.resource_type,
            "resource_id": resource.resource_id,
            "knowledge_point": issue.get("knowledge_point") if issue.get("knowledge_point") in nodes else None,
            "description": f"{location(issue['description'])}：{_ISSUE_LABELS[issue['code']]}"})
    normalized["revision_instructions"] = []
    for instruction in raw.get("revision_instructions", []):
        codes = instruction.get("issue_codes") or []
        if (not codes or set(codes) - set(_ISSUE_LABELS) or instruction.get("target_claim_ids")
                or instruction.get("target_resource_type") != resource.resource_type):
            raise ValueError("assessment summary revision invalid")
        normalized["revision_instructions"].append({**instruction,
            "action": f"修正{location(instruction['action'])}；按问题码处理整卷问题，保持冻结目标、各题证据与题型配额。"})
    return normalized

def normalize_node_tier_review(raw: dict, resource, state: dict) -> dict:
    """Remove false difficulty findings when the target-node contract passes."""

    if resource.resource_type != "复习清单":
        return raw
    if node_tier_difficulty_review(resource, state) is not None:
        return raw
    if state.get("constraints", {}).get("target_tier") is None:
        return raw
    normalized = dict(raw)
    normalized["difficulty_match"] = True
    issues = [item for item in normalized.get("issues", []) if item.get("code") != "difficulty_mismatch"]
    instructions = [
        item for item in normalized.get("revision_instructions", [])
        if "difficulty_mismatch" not in item.get("issue_codes", [])
    ]
    normalized["issues"] = issues
    normalized["revision_instructions"] = instructions
    if normalized.get("decision") == "revise" and not issues and not instructions:
        normalized["decision"] = "approve"
        normalized["suggestion"] = "目标能力节点阶级与资源难度一致；继续按证据和结构审核。"
    return normalized

def decorate_review_items(review: dict, *, run_id: str, generation_attempt: int) -> dict:
    decorated = dict(review)
    decorated["issues"] = [
        {
            "issue_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{run_id}:review:{generation_attempt}:issue:{index}",
                )
            ),
            **item,
        }
        for index, item in enumerate(review.get("issues", []), start=1)
        if isinstance(item, dict)
    ]
    decorated["revision_instructions"] = [
        {
            "instruction_id": str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{run_id}:review:{generation_attempt}:instruction:{index}",
                )
            ),
            **item,
        }
        for index, item in enumerate(review.get("revision_instructions", []), start=1)
        if isinstance(item, dict)
    ]
    return decorated

def normalize_review_result(*, output, findings=(), resource_context=None) -> dict:
    raw = output.model_dump(mode="python") if hasattr(output, "model_dump") else dict(output)
    if resource_context is not None and resource_context.assessment_payload:
        raw = _assessment_summary_projection(raw=raw, resource=resource_context)
    failed = [finding for finding in findings if finding.get("codes")]
    if not failed:
        return raw
    resource = resource_context
    # All failures determine the decision; only the public summary is bounded.
    issues = [{"code": code, "severity": "high", "resource_type": resource.resource_type,
               "resource_id": resource.resource_id, "knowledge_point": finding["skill_node_id"],
               "description": f"{finding['question_id']}：{finding['reason']}"}
              for finding in failed for code in finding["codes"]]
    severity = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    raw["issues"] = sorted(issues + raw.get("issues", []), key=lambda i: severity[i["severity"]])[:3]
    if raw.get("decision") not in {"reject", "human_review"}:
        raw["decision"] = "revise"
    raw["revision_instructions"] = [{
        "issue_codes": sorted({code for f in failed for code in f["codes"]}),
        "target_resource_type": resource.resource_type,
        "action": "按内部逐题定位修正全部失败题；保持冻结节点、题型配额和各题 Evidence 范围。", "priority": 1,
    }]
    return raw
