"""Deterministic gates, independent of model invocation and workflow routing."""

from app.models.shared.agent_contracts import PracticeGuidePackageV3
from app.models.shared.assessment import (
    ASSESSMENT_QUESTION_QUOTAS, ASSESSMENT_SCORE_BY_TYPE,
    ASSESSMENT_SCORE_DECIMAL_PLACES, ASSESSMENT_TOTAL_SCORE,
)

STRUCTURED_MARKDOWN_SECTIONS = {
    "复习清单": ("使用说明", "节点知识小结", "答案与证据解释", "自评与下一步"),
    "案例分析": ("案例背景", "任务目标", "分析过程", "参考方案", "复盘要点"),
    "个性化纠错训练包": ("本次强化目标", "薄弱模式概览", "参考答案与分层反馈", "达标标准", "后续复习动作", "总结"),
}

def node_tier_difficulty_review(resource, state: dict) -> dict | None:
    """Enforce difficulty from the frozen target-node tier, not surface form."""

    if resource.resource_type != "复习清单":
        return None
    constraints = state.get("constraints", {})
    target_tier = constraints.get("target_tier")
    expected_difficulty = state.get("difficulty_preference")
    target_nodes = {str(item) for item in state.get("target_skill_nodes", []) if str(item).strip()}
    covered_nodes = {str(item) for item in resource.knowledge_points if str(item).strip()}
    if target_tier is None or not expected_difficulty:
        return None

    valid = (
        resource.difficulty == expected_difficulty
        and bool(target_nodes)
        and bool(covered_nodes)
        and covered_nodes <= target_nodes
    )
    if valid:
        return None
    return {
        "decision": "revise",
        "hallucination_score": 0.0,
        "issues": [{
            "code": "difficulty_mismatch",
            "severity": "high",
            "resource_type": resource.resource_type,
            "knowledge_point": None,
            "description": "资源覆盖节点未满足冻结目标阶级，不能据此证明资源难度匹配。",
        }],
        "difficulty_match": False,
        "coverage_rate": 0.0,
        "suggestion": "仅覆盖冻结目标能力节点，并保持资源难度与目标阶级一致。",
        "revision_instructions": [{
            "issue_codes": ["difficulty_mismatch"],
            "target_resource_type": resource.resource_type,
            "action": "按冻结目标节点阶级重建资源，不以题型或措辞替代节点覆盖。",
            "priority": 1,
        }],
    }

def check_markdown_structure(resource) -> dict | None:
    """Apply hard specialized safety checks before the advisory LLM review."""

    if resource.resource_type == "分阶测试题" and resource.assessment_payload is not None:
        blocks = resource.assessment_payload.get("node_blocks", [])
        expected_fields = ("single_choice_questions", "multiple_choice_questions", "short_answer_questions")
        questions = [
            question
            for block in blocks
            for field_name in expected_fields
            for question in block.get(field_name, [])
        ] if isinstance(blocks, list) else []
        score_valid = (
            round(sum(float(item.get("max_score", 0)) for item in questions), ASSESSMENT_SCORE_DECIMAL_PLACES) == ASSESSMENT_TOTAL_SCORE
            and all(
                round(
                    sum(float(item.get("max_score", 0)) for item in questions if item.get("question_type") == question_type),
                    ASSESSMENT_SCORE_DECIMAL_PLACES,
                ) == ASSESSMENT_SCORE_BY_TYPE[question_type] * quota
                for question_type, quota in ASSESSMENT_QUESTION_QUOTAS.items()
            )
            and all(
                round(float(item.get("max_score", 0)), ASSESSMENT_SCORE_DECIMAL_PLACES) == float(item.get("max_score", 0))
                for item in questions
            )
        )
        valid = bool(blocks) and all(
            len(block.get("single_choice_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["single_choice"]
            and len(block.get("multiple_choice_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["multiple_choice"]
            and len(block.get("short_answer_questions", [])) == ASSESSMENT_QUESTION_QUOTAS["short_answer"]
            and all(item.get("difficulty_stage") == "基础" for item in block.get("single_choice_questions", []))
            and all(item.get("difficulty_stage") == "进阶" for item in block.get("multiple_choice_questions", []))
            and all(item.get("difficulty_stage") == "挑战" for item in block.get("short_answer_questions", []))
            and all(block.get(field_name) for field_name in expected_fields)
            for block in blocks
        ) and score_valid
        if valid and all(f"### {title}" in (resource.content_text or "") for title in ("单选题（基础）", "多选题（进阶）", "问答题（挑战）")):
            return None
        return {
            "decision": "revise", "hallucination_score": 0.0,
            "issues": [{"code": "structure_quality", "severity": "high", "resource_type": resource.resource_type,
                        "knowledge_point": None, "description": "结构化测试题必须每节点含 2 基础单选、2 进阶多选、2 挑战问答，并按题型与阶段渲染。"}],
            "difficulty_match": True, "coverage_rate": 0.0, "suggestion": "按固定 V2 题组结构重建。",
            "revision_instructions": [{"issue_codes": ["structure_quality"], "target_resource_type": resource.resource_type,
                                        "action": "恢复每节点固定题型配额、题型阶段映射及 Markdown 分类。", "priority": 1}],
        }
    if resource.resource_type == "复习清单" and resource.review_practice_payload is not None:
        package = resource.review_practice_payload
        blocks = package.get("node_blocks", []) if isinstance(package, dict) else []
        valid = bool(blocks) and all(
            1 <= len(block.get("recall_questions", [])) <= 4
            and 1 <= len(block.get("distinction_questions", [])) <= 4
            and len(str(block.get("knowledge_summary") or "").strip()) >= 100
            and bool(block.get("summary_evidence_ids"))
            and set(block.get("summary_evidence_ids") or []) <= set(block.get("evidence_ids") or [])
            and len(block.get("omitted_slots", [])) == 10 - len(block.get("recall_questions", [])) - len(block.get("distinction_questions", [])) - (
                len(block.get("example_recognition_questions") or [])
                or int(bool(block.get("example_recognition")))
            )
            for block in blocks
        )
        content = resource.content_text or ""
        if valid and "### 节点知识小结" in content and content.find("## 答案与证据解释") > content.find("## 节点") and "<script" not in content.lower():
            return None
        return {"decision": "revise", "hallucination_score": 0.0, "issues": [{"code": "structure_quality", "severity": "high", "resource_type": resource.resource_type, "knowledge_point": None, "description": "主动回忆清单必须满足每节点最低 1+1+0、带证据的节点知识小结、缺省槽位可审计，且答案统一位于文末。"}], "difficulty_match": True, "coverage_rate": 0.0, "suggestion": "按 V3 主动回忆结构重建。", "revision_instructions": [{"issue_codes": ["structure_quality"], "target_resource_type": resource.resource_type, "action": "恢复节点题组、知识小结、缺省原因和文末答案区。", "priority": 1}]}
    # Correction packages are prose-first. Their Markdown headings and order
    # are advisory and must not block ordinary or Claim review. Keep the script
    # check as a safety boundary, not a formatting requirement.
    if resource.resource_type == "个性化纠错训练包":
        content = (resource.content_text or "").strip()
        if "<script" not in content.lower():
            return None
        return {
            "decision": "revise",
            "hallucination_score": 0.0,
            "issues": [{
                "code": "structure_quality",
                "severity": "high",
                "resource_type": resource.resource_type,
                "knowledge_point": None,
                "description": "检测到脚本标记，资源只能包含安全的 Markdown 文本。",
            }],
            "difficulty_match": True,
            "coverage_rate": 0.0,
            "suggestion": "删除脚本标记后再审核。",
            "revision_instructions": [{
                "issue_codes": ["structure_quality"],
                "target_resource_type": resource.resource_type,
                "action": "删除 HTML/script 标记，仅保留安全的学习文本。",
                "priority": 1,
            }],
        }

    required_sections = STRUCTURED_MARKDOWN_SECTIONS.get(resource.resource_type)
    if not required_sections:
        return None
    content = (resource.content_text or "").strip()
    missing_sections = [
        section for section in required_sections
        if (f"### {section}" if section == "节点知识小结" else f"## {section}") not in content
    ]
    has_script = "<script" in content.lower()
    correction_sections = ("错误模式", "核心概念补救", "正误对照", "完整示例", "引导式练习", "同构练习", "迁移练习")
    correction_missing = (
        [section for section in correction_sections if f"### {section}" not in content]
        if resource.resource_type == "个性化纠错训练包" else []
    )
    if content.startswith("# ") and not missing_sections and not correction_missing and not has_script:
        return None
    description = (
        "缺少唯一一级标题。"
        if not content.startswith("# ")
        else f"缺少必要章节：{'、'.join([*missing_sections, *correction_missing])}。"
        if missing_sections or correction_missing
        else "检测到脚本标记，资源只能包含 Markdown 文本。"
    )
    return {
        "decision": "revise",
        "hallucination_score": 0.0,
        "issues": [{
            "code": "structure_quality",
            "severity": "high",
            "resource_type": resource.resource_type,
            "knowledge_point": None,
            "description": description,
        }],
        "difficulty_match": True,
        "coverage_rate": 0.0,
        "suggestion": "请补齐资源结构后重新生成。",
        "revision_instructions": [{
            "issue_codes": ["structure_quality"],
            "target_resource_type": resource.resource_type,
            "action": description,
            "priority": 1,
        }],
    }

def check_practice_structure(resource) -> dict | None:
    """Keep the practice-guide release gate focused on usable structure.

    Generated instructional snippets can legitimately show credentials or
    script-like text. Those snippets are not treated as live code or secrets,
    so they must not cause a retry; correctness is assessed by the normal
    evidence and content review path.
    """
    package = getattr(resource, "practice_guide_payload", None)
    try:
        valid_package = isinstance(package, dict) and package.get("schema_version") == "3.0"
        if valid_package:
            PracticeGuidePackageV3.model_validate(
                {key: value for key, value in package.items() if key != "payload_hash"}
            )
    except ValueError:
        valid_package = False
    if not valid_package:
        return {
            "decision": "revise", "hallucination_score": 0.0,
            "issues": [{"code": "structure_quality", "severity": "high",
                        "resource_type": resource.resource_type, "knowledge_point": None,
                        "description": "实操指南缺少有效的 V3 固定阶段 JSON，禁止仅以 Markdown 发布。"}],
            "difficulty_match": True, "coverage_rate": 0.0,
            "suggestion": "重新生成并持久化四阶段结构化 JSON，再渲染 Markdown。",
            "revision_instructions": [{"issue_codes": ["structure_quality"],
                                        "target_resource_type": resource.resource_type,
                                        "action": "生成有效的 V3 固定阶段 JSON，并由该 JSON 确定性渲染 Markdown。", "priority": 1}],
        }
    content = resource.content_text or ""
    required_sections = ("准备阶段", "实操阶段", "验证阶段", "复盘阶段")
    missing_sections = [section for section in required_sections if section not in content]
    if missing_sections:
        description = f"缺少必要章节：{'、'.join(missing_sections)}。"
        return {
            "decision": "revise", "hallucination_score": 0.0,
            "issues": [{"code": "procedure_error", "severity": "high",
                        "resource_type": resource.resource_type, "knowledge_point": None,
                        "description": description}],
            "difficulty_match": True, "coverage_rate": 1.0,
            "suggestion": "请按检查项修正后重新生成。",
            "revision_instructions": [{"issue_codes": ["procedure_error"],
                                        "target_resource_type": resource.resource_type,
                                        "action": description, "priority": 1}],
        }
    return None


def check_resource_structure(*, resource, spec=None, context=None) -> dict | None:
    """None permits semantic review; a failure is an existing revision summary."""
    if resource.resource_type == "实操指南":
        return check_practice_structure(resource)
    return check_markdown_structure(resource)
