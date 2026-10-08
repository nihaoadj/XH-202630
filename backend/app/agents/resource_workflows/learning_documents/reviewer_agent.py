import json
import uuid
from datetime import datetime, timezone
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.learning_documents.state import AgentState
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.core.retrieval.evidence import source_refs_are_scoped
from app.core.security.errors import ErrorCode
from app.models.shared.agent_contracts import (
    NodeResult,
    PracticeGuidePackageV3,
    ReviewLLMOutput,
    ReviewerInput,
    ReviewerOutput,
    build_trace_item,
    make_error_info,
    start_step,
)
from app.models.shared.llm import LLMCallContext
from app.models.shared.assessment import (
    ASSESSMENT_QUESTION_QUOTAS,
    ASSESSMENT_SCORE_BY_TYPE,
    ASSESSMENT_SCORE_DECIMAL_PLACES,
    ASSESSMENT_TOTAL_SCORE,
)
from app.models.shared.workflow import ResourceStatus, ReviewDecision, StepStatus
from app.agents.shared.policies import decide_review, locked_human_review_resource_ids
from app.agents.shared.validators import revision_instructions_are_valid
from app.agents.resource_workflows.learning_documents.generator_agent import progress_summary
from app.agents.resource_workflows.learning_documents.specialized_reviews.assessment_scope import (
    review_assessment_scope,
)


REVIEW_PROMPT = """你是一名严格的内容审核 Agent。请对以下学习资源进行审核，重点检查：
1. 是否存在与专业知识片段不符的事实错误（幻觉）。
2. 操作步骤是否符合行业规范。
3. 资源难度是否与学习者水平匹配。对“复习清单”，难度审核的首要依据是资源覆盖的能力节点是否属于冻结的目标节点阶级，
   不是题目数量、题型表面复杂度或文字中是否出现“综合/挑战”等词。高级难度必须覆盖高级（tier=3）能力节点；
   中级必须覆盖中级（tier=2）节点；初级必须覆盖初级（tier=1）节点。复习清单保持主动回忆结构，
   不能因为其包含回忆题或辨析题就判定高级节点“不够高级”。其他资源沿用其既有的难度审核口径。
4. 内容是否完整覆盖目标知识点。

资源类型解释：当 resource_type 为“分阶测试题”时，V2 固定结构是每个能力节点恰有 2 道单选（基础）、2 道多选（进阶）、2 道问答（挑战）。应同时审核题型配额、题型与难度阶段映射、可判定性、证据范围和知识点覆盖。
当输入含有“内部结构化题卷”时，逐题范围与证据审核已经由独立专用审核器完成。你只做包级补充审核：
不得复述题干、选项、正确答案、参考答案、rubric、evidence 或逐题清单；不得重新解释已通过的逐题范围结论。
复习清单标题是服务端按批次主题生成的展示标题；审核内容是否匹配时，以当前目标能力节点和 Evidence 为准，
不要仅因标题比当前节点更宽泛就提出覆盖或结构问题。
对于“个性化纠错训练包”，Markdown 标题、章节顺序、章节拆分和小节命名仅是生成建议；不要仅因这些排版差异提出 structure_quality 或要求返工。仍需审核事实、Evidence 范围、知识点覆盖、难度和练习内容是否可用。
若没有新的包级事实、结构或难度问题，直接输出 approve 和空 issues；每个字段使用最短必要中文。

请用 JSON 格式输出：
{
  "decision": "approve" | "revise" | "reject" | "human_review",
  "hallucination_score": float (0-1, 越高表示幻觉越严重),
  "issues": [{
    "code": "factual_risk|evidence_gap|procedure_error|difficulty_mismatch|coverage_gap|structure_quality|other",
    "severity": "low|medium|high|critical",
    "resource_type": "目标资源类型或 null",
    "knowledge_point": "目标知识点或 null",
    "description": "问题描述"
  }],
  "difficulty_match": bool,
  "coverage_rate": float (0-1),
  "suggestion": "审核判断或改进建议",
  "revision_instructions": [{
    "issue_codes": ["关联问题码"],
    "target_resource_type": "必须是待审核资源类型之一",
    "action": "可直接执行的修改要求",
    "priority": 1
  }]
}
revise 必须包含至少一条 revision_instructions；approve 不得包含 revision_instructions。
最多输出 3 条 issues、1 条 revision_instruction；每条描述与 action 不超过 120 个中文字符。
不要包含额外解释。
"""


STRUCTURED_MARKDOWN_SECTIONS = {
    "复习清单": ("使用说明", "节点知识小结", "答案与证据解释", "自评与下一步"),
    "案例分析": ("案例背景", "任务目标", "分析过程", "参考方案", "复盘要点"),
    "个性化纠错训练包": ("本次强化目标", "薄弱模式概览", "参考答案与分层反馈", "达标标准", "后续复习动作", "总结"),
}


def _node_tier_difficulty_review(resource, state: AgentState) -> dict | None:
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


def _normalize_node_tier_review(raw: dict, resource, state: AgentState) -> dict:
    """Remove false difficulty findings when the target-node contract passes."""

    if resource.resource_type != "复习清单":
        return raw
    if _node_tier_difficulty_review(resource, state) is not None:
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


def _deterministic_resource_structure_review(resource) -> dict | None:
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


def _internal_assessment_review_payload(resource) -> str:
    """Expose the canonical answer-bearing payload only to the internal reviewer."""
    if resource.resource_type != "分阶测试题" or not resource.assessment_payload:
        return ""
    return json.dumps({
        "audit_scope": "internal_only_do_not_repeat_answers_in_review",
        "assessment_package": resource.assessment_payload,
    }, ensure_ascii=False, separators=(",", ":"))


def _deterministic_practice_guide_review(resource) -> dict:
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
    return {
        "decision": "approve", "hallucination_score": 0.0, "issues": [],
        "difficulty_match": True, "coverage_rate": 1.0,
        "suggestion": "实操指南已通过结构检查；内容正确性按通用证据审核结果判定。",
        "revision_instructions": [],
    }


def _fail_closed_review_error(error):
    """Keep review outages safe without converting a valid artifact into a failed Run.

    Review is a release gate, not an artifact producer.  If it cannot produce
    a decision, the only safe result is ``human_review`` and an unpublished
    resource.  This does not use the general degraded-generation opt-in: that
    policy applies to fabricating replacement content, whereas this branch
    creates no content and can never auto-publish.
    """

    return error


def _decorate_review_items(review: dict, *, run_id: str, generation_attempt: int) -> dict:
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


def review_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
) -> dict:
    """Review canonical text resources independently and aggregate deterministically."""
    node_input = ReviewerInput.model_validate(state)
    # A revision run replaces only the resource types named by the previous
    # review instructions.  Previously approved siblings are immutable from a
    # review perspective: re-reviewing them allocates fresh review IDs for an
    # unchanged resource and can make the durable resource/review projections
    # disagree with the newly generated revision.  Review only canonical text
    # artifacts that have not reached a terminal approval/rejection decision.
    #
    # The initial generation emits ``pending_review`` for every resource, while
    # a targeted revision emits a new ``pending_review`` version for just the
    # requested type.  ``unreviewed_draft`` is retained for callers that invoke
    # this node directly with a draft state.
    reviewable_statuses = {
        None,
        ResourceStatus.PENDING_REVIEW.value,
        ResourceStatus.UNREVIEWED_DRAFT.value,
        ResourceStatus.HUMAN_REVIEW.value,
    }
    resources = [
        item
        for item in node_input.generated_resources
        if item.representation.value == "text"
        and item.review_status in reviewable_statuses
    ]
    locked_resource_ids = locked_human_review_resource_ids(
        resources,
        state.get("resource_executions", []),
    )
    evidence = node_input.retrieved_evidence
    step_context = start_step(state, attempt=node_input.generation_attempt)
    review_ids = {resource.resource_id: str(uuid.uuid4()) for resource in resources}
    context = "\n\n".join(f"[证据 {item.evidence_id}] {item.excerpt}" for item in evidence)
    results: dict[str, dict] = {}
    errors = []
    trace_error = None
    last_llm_result = None

    if not resources:
        try:
            last_llm_result = llm_gateway.invoke_structured(
                messages=[
                    SystemMessage(content=REVIEW_PROMPT),
                    HumanMessage(content="待审核资源为空；禁止自动批准。"),
                ],
                output_schema=ReviewLLMOutput,
                context=LLMCallContext(
                    run_id=node_input.run_id,
                    step_id=step_context["step_id"],
                    node_name="reviewer",
                    schema_name=ReviewLLMOutput.__name__,
                    generation_attempt=node_input.generation_attempt,
                    workflow_deadline_at=state.get("workflow_deadline_at"),
                ),
                options=llm_gateway.options_for("reviewer", temperature=0.0),
            )
            trace_error = _fail_closed_review_error(make_error_info(
                ErrorCode.WORKFLOW_CONTRACT_INVALID,
                source="reviewer",
                attempt=node_input.generation_attempt,
                category="contract",
                safe_detail="no_text_resources",
            ))
        except LLMGatewayError as exc:
            trace_error = _fail_closed_review_error(exc.error)
            last_llm_result = exc
        errors.append(trace_error.model_dump(mode="json"))
        results["__missing_resource__"] = {
            "decision": "human_review",
            "passed": False,
            "hallucination_score": 1.0,
            "coverage_rate": 0.0,
            "difficulty_match": False,
            "issues": [],
            "revision_instructions": [],
        }

    for resource in resources:
        invalid_source_refs = not source_refs_are_scoped(resource.source_refs, evidence)
        error = None
        specialized_review = None
        tier_contract = node_input.constraints.get("target_tier")
        expected_difficulty = node_input.difficulty_preference
        node_tier_review = _node_tier_difficulty_review(resource, state)
        if resource.resource_id in locked_resource_ids:
            raw = {
                "decision": "human_review",
                "hallucination_score": 1.0,
                "issues": [{
                    "code": "other",
                    "severity": "high",
                    "resource_type": resource.resource_type,
                    "resource_id": resource.resource_id,
                    "knowledge_point": None,
                    "description": "资源生成或产物校验失败，自动审核不得覆盖人工复核状态。",
                }],
                "difficulty_match": False,
                "coverage_rate": 0.0,
                "suggestion": "保持未发布，等待人工复核。",
                "revision_instructions": [],
            }
        elif node_tier_review is not None:
            raw = node_tier_review
        elif tier_contract is not None and resource.difficulty != expected_difficulty:
            raw = {
                "decision": "revise", "hallucination_score": 0.0,
                "issues": [{"code": "other", "severity": "high", "resource_type": resource.resource_type,
                            "resource_id": resource.resource_id, "knowledge_point": None,
                            "description": "资源难度与冻结的能力节点阶级不一致。"}],
                "difficulty_match": False, "coverage_rate": 1.0,
                "suggestion": "按冻结阶级重建资源规格。",
                "revision_instructions": [{"target_resource_type": resource.resource_type,
                                           "instruction": "将资源难度调整为冻结目标阶级。"}],
            }
        elif invalid_source_refs:
            error = _fail_closed_review_error(make_error_info(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID, source="reviewer",
                attempt=node_input.generation_attempt, category="evidence",
                safe_detail=f"resource_source_refs:{resource.resource_id}:out_of_scope"))
            raw = {"decision": "human_review", "hallucination_score": 1.0,
                   "issues": [{"code": "evidence_gap", "severity": "critical",
                               "resource_type": resource.resource_type, "knowledge_point": None,
                               "description": "资源引用未能映射到本次检索证据"}],
                   "difficulty_match": False, "coverage_rate": 0.0,
                   "suggestion": "引用证据不完整，禁止自动批准。", "revision_instructions": []}
        elif structured_review := _deterministic_resource_structure_review(resource):
            raw = structured_review
        elif resource.resource_type == "分阶测试题" and resource.assessment_payload is not None:
            try:
                specialized_review = review_assessment_scope(
                    resource=resource,
                    evidence=evidence,
                    target_skill_nodes=list(state.get("target_skill_nodes", [])),
                    llm_gateway=llm_gateway,
                    context=LLMCallContext(
                        run_id=node_input.run_id, step_id=step_context["step_id"],
                        node_name="assessment_scope_reviewer",
                        schema_name="AssessmentScopeReviewV1",
                        generation_attempt=node_input.generation_attempt,
                        workflow_deadline_at=state.get("workflow_deadline_at"),
                    ),
                )
                if not specialized_review.passed:
                    raw = {
                        "decision": "revise", "hallucination_score": 0.0,
                        "issues": specialized_review.issues,
                        "difficulty_match": True, "coverage_rate": 0.0,
                        "suggestion": "逐题范围审核发现越界或证据不足，需定向重建。",
                        "revision_instructions": specialized_review.revision_instructions,
                    }
                else:
                    internal_assessment = _internal_assessment_review_payload(resource)
                    user_input = (f"专业知识片段：\n{context}\n\n待审核的唯一资源：\n"
                                  f"resource_id={resource.resource_id}\nresource_type={resource.resource_type}\n"
                                  f"难度={resource.difficulty}\n{resource.content_text or ''}\n\n"
                                  f"目标难度：{node_input.difficulty_preference or '按画像与诊断结果'}\n"
                                  f"生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}"
                                  f"\n\n仅供内部审核的完整结构化题卷（含答案、rubric 与 evidence ID；不得在输出中复述）：\n{internal_assessment}")
                    last_llm_result = llm_gateway.invoke_structured(
                        messages=[SystemMessage(content=REVIEW_PROMPT), HumanMessage(content=user_input)],
                        output_schema=ReviewLLMOutput,
                        context=LLMCallContext(run_id=node_input.run_id, step_id=step_context["step_id"],
                            node_name="reviewer", schema_name=ReviewLLMOutput.__name__,
                            generation_attempt=node_input.generation_attempt,
                            workflow_deadline_at=state.get("workflow_deadline_at")),
                        options=llm_gateway.options_for("reviewer", temperature=0.0).model_copy(
                            update={"max_output_tokens": 12288}
                        ))
                    raw = last_llm_result.output.model_dump(mode="python")
            except LLMGatewayError as exc:
                error = _fail_closed_review_error(exc.error)
                last_llm_result = exc
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "测评范围审核不可用，无法安全完成自动审核"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "", "revision_instructions": []}
            except ValueError:
                error = _fail_closed_review_error(make_error_info(
                    ErrorCode.LLM_OUTPUT_SCHEMA_INVALID, source="assessment_scope_reviewer",
                    attempt=node_input.generation_attempt, category="assessment_scope"))
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "测评范围审核结果无效，无法安全完成自动审核"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "", "revision_instructions": []}
        elif resource.resource_type == "实操指南":
            raw = _deterministic_practice_guide_review(resource)
        else:
            internal_assessment = _internal_assessment_review_payload(resource)
            user_input = (f"专业知识片段：\n{context}\n\n待审核的唯一资源：\n"
                          f"resource_id={resource.resource_id}\nresource_type={resource.resource_type}\n"
                          f"难度={resource.difficulty}\n{resource.content_text or ''}\n\n"
                          f"目标难度：{node_input.difficulty_preference or '按画像与诊断结果'}\n"
                          f"生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}"
                          + (f"\n\n仅供内部审核的完整结构化题卷（含答案、rubric 与 evidence ID；不得在输出中复述）：\n{internal_assessment}"
                             if internal_assessment else ""))
            try:
                last_llm_result = llm_gateway.invoke_structured(
                    messages=[SystemMessage(content=REVIEW_PROMPT), HumanMessage(content=user_input)],
                    output_schema=ReviewLLMOutput,
                    context=LLMCallContext(run_id=node_input.run_id, step_id=step_context["step_id"],
                        node_name="reviewer", schema_name=ReviewLLMOutput.__name__,
                        generation_attempt=node_input.generation_attempt,
                        workflow_deadline_at=state.get("workflow_deadline_at")),
                    options=llm_gateway.options_for("reviewer", temperature=0.0).model_copy(
                        update={"max_output_tokens": 12288}
                    ))
                raw = last_llm_result.output.model_dump(mode="python")
            except LLMGatewayError as exc:
                error = _fail_closed_review_error(exc.error)
                last_llm_result = exc
                raw = {"decision": "human_review", "hallucination_score": 0.5,
                       "issues": [{"code": "evidence_gap", "severity": "high",
                                   "resource_type": resource.resource_type, "knowledge_point": None,
                                   "description": "审核能力暂不可用，无法安全完成自动审核"}],
                       "difficulty_match": False, "coverage_rate": 0.0,
                       "suggestion": "", "revision_instructions": []}
        raw = _normalize_node_tier_review(raw, resource, state)
        decorated = _decorate_review_items(raw, run_id=f"{node_input.run_id}:{resource.resource_id}",
                                           generation_attempt=node_input.generation_attempt)
        if specialized_review is not None:
            decorated["specialized_reviews"] = {
                "assessment_scope": {
                    "passed": specialized_review.passed,
                    "findings": specialized_review.findings,
                }
            }
        valid = revision_instructions_are_valid(decorated.get("revision_instructions", []),
                                                [resource.resource_type])
        decision = (ReviewDecision.HUMAN_REVIEW if error else decide_review(
            decorated, valid_source_refs=not invalid_source_refs,
            valid_revision_instructions=valid))
        decorated.update({"passed": decision == ReviewDecision.APPROVE,
                          "decision": decision.value, "status": decision.value,
                          "review_id": review_ids[resource.resource_id],
                          "resource_id": resource.resource_id,
                          "resource_spec_id": resource.resource_spec_id,
                          "resource_type": resource.resource_type,
                          "revision_count": node_input.revision_count})
        results[resource.resource_id] = decorated
        if error:
            trace_error = trace_error or error
            errors.append(error.model_dump(mode="json"))

    decisions = [ReviewDecision(item["decision"]) for item in results.values()]
    aggregate_decision = next((value for value in (
        ReviewDecision.HUMAN_REVIEW, ReviewDecision.REJECT, ReviewDecision.REVISE)
        if value in decisions), ReviewDecision.APPROVE)
    issues = [item for result in results.values() for item in result.get("issues", [])]
    instructions = [item for result in results.values()
                    for item in result.get("revision_instructions", [])]
    review = {
        "passed": aggregate_decision == ReviewDecision.APPROVE,
        "decision": aggregate_decision.value, "status": aggregate_decision.value,
        "review_ids": review_ids, "revision_count": node_input.revision_count,
        "issues": issues, "revision_instructions": instructions,
        "hallucination_score": max((item.get("hallucination_score", 1.0)
                                    for item in results.values()), default=1.0),
        "coverage_rate": min((item.get("coverage_rate", 0.0)
                              for item in results.values()), default=0.0),
        "difficulty_match": all(item.get("difficulty_match", False)
                                for item in results.values()),
        "suggestion": "资源级审核结果已按最严格结论聚合。",
    }
    status = (
        StepStatus.DEGRADED
        if errors
        else StepStatus.HUMAN_REVIEW
        if locked_resource_ids
        else StepStatus.SUCCESS
    )
    now = datetime.now(timezone.utc)
    reviewed_resources = []
    executions = []
    execution_by_resource = {
        item.get("resource_id"): dict(item)
        for item in state.get("resource_executions", [])
    }
    for resource in node_input.generated_resources:
        canonical_resource_id = resource.resource_id
        result = results.get(canonical_resource_id)
        if result is None:
            reviewed_resources.append(resource)
            continue
        inherited_review_id = review_ids.get(canonical_resource_id)
        if inherited_review_id is None:
            raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)
        decision = result["decision"]
        review_status = {
            "approve": "approved", "revise": "revision_requested",
            "reject": "rejected", "human_review": "human_review",
        }[decision]
        published = (
            decision == "approve"
            and not state.get("include_claim_check", False)
            and not (
                state.get("generation_mode") == "strict"
                and (state.get("errors") or errors)
            )
        )
        reviewed_resources.append(resource.model_copy(update={
            "review_id": inherited_review_id,
            "review_status": review_status,
            "publication_status": "published" if published else "unpublished",
            "published_at": now if published else None,
            "legacy_reviewer_score": result.get("hallucination_score"),
            "hallucination_rate": result.get("hallucination_score"),
            "difficulty_match": result.get("difficulty_match"),
        }))
        execution = execution_by_resource.get(resource.resource_id, {
            "resource_spec_id": resource.resource_spec_id,
            "resource_type": resource.resource_type,
            "representation": resource.representation.value,
            "attempt": node_input.generation_attempt,
            "resource_id": resource.resource_id,
        })
        execution.update({"review_id": inherited_review_id,
                          "resource_execution_state": {
                              "approve": "approved", "revise": "revision_requested",
                              "reject": "failed", "human_review": "human_review",
                          }[decision]})
        executions.append(execution)
    untouched_ids = {item.get("resource_id") for item in executions}
    executions.extend(item for item in state.get("resource_executions", [])
                      if item.get("resource_id") not in untouched_ids)
    trace_item = build_trace_item(
        state,
        agent_name="reviewer",
        action="审核纠偏",
        status=status,
        input_summary=f"资源数：{len(resources)}；证据数：{len(evidence)}；生成轮次：{node_input.generation_attempt}",
        output_summary=f"决策：{aggregate_decision.value}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
        decision_reason=review.get("suggestion", "根据知识库证据、事实一致性、覆盖率和难度匹配给出审核结论。"),
        evidence_refs=[item.evidence_id for item in evidence[:5]],
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review_ids.values()),
        error=trace_error,
        attempt=node_input.generation_attempt,
        step_context=step_context,
        llm_metadata=last_llm_result.trace_metadata() if last_llm_result else None,
    )

    return {
        "review_result": review,
        # A targeted revision reviews only the newly generated resource types.
        # Preserve decisions for untouched siblings so the final aggregation
        # cannot turn a previously approved lecture into human review merely
        # because another resource still needs revision.
        "resource_review_results": {
            **state.get("resource_review_results", {}),
            **results,
        },
        "generated_resources": reviewed_resources,
        "resource_executions": executions,
        "resource_progress_summary": progress_summary(executions),
        "current_node": "reviewer",
        "trace": [trace_item],
        "errors": errors,
    }
