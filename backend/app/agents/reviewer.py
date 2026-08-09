import json
import uuid
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.core.evidence import source_refs_are_scoped
from app.core.errors import ErrorCode
from app.models.agent_contracts import (
    NodeResult,
    ReviewLLMOutput,
    ReviewerInput,
    ReviewerOutput,
    build_trace_item,
    make_error_info,
    require_agent_fallback,
    start_step,
)
from app.models.llm import LLMCallContext
from app.models.workflow import ReviewDecision, StepStatus
from app.agents.policies import decide_review
from app.agents.validators import revision_instructions_are_valid


REVIEW_PROMPT = """你是一名严格的内容审核 Agent。请对以下学习资源进行审核，重点检查：
1. 是否存在与专业知识片段不符的事实错误（幻觉）。
2. 操作步骤是否符合行业规范。
3. 资源难度是否与学习者水平匹配。
4. 内容是否完整覆盖目标知识点。

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
不要包含额外解释。
"""


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
    """审核纠偏 Agent：事实核查、幻觉检测、难度匹配"""
    node_input = ReviewerInput.model_validate(state)
    resources = node_input.generated_resources
    evidence = node_input.retrieved_evidence
    step_context = start_step(state, attempt=node_input.generation_attempt)
    review_ids = {
        resource.resource_id: str(uuid.uuid4())
        for resource in resources
    }

    context = "\n\n".join(
        f"[证据 {item.evidence_id}] {item.excerpt}"
        for item in evidence[:5]
    )
    resource_text = "\n\n".join(
        [f"[{r.resource_type}] 难度：{r.difficulty}\n{r.content_text or ''}" for r in resources]
    )

    user_input = f"""
专业知识片段：
{context}

待审核资源：
{resource_text}

目标难度：{node_input.difficulty_preference or '按画像与诊断结果'}
生成约束：{json.dumps(node_input.constraints, ensure_ascii=False)}
"""
    llm_result = None
    error = None
    invalid_source_refs = any(
        not source_refs_are_scoped(resource.source_refs, evidence)
        for resource in resources
    )
    if invalid_source_refs:
        error = require_agent_fallback(
            state,
            make_error_info(
                ErrorCode.EVIDENCE_PROVENANCE_INVALID,
                source="reviewer",
                attempt=node_input.generation_attempt,
                category="evidence",
                safe_detail="resource_source_refs:out_of_scope",
            ),
        )
        review = {
            "decision": ReviewDecision.HUMAN_REVIEW.value,
            "passed": False,
            "hallucination_score": 1.0,
            "issues": [{
                "code": "evidence_gap",
                "severity": "critical",
                "resource_type": None,
                "knowledge_point": None,
                "description": "资源引用未能映射到本次检索证据",
            }],
            "difficulty_match": False,
            "coverage_rate": 0.0,
            "suggestion": "引用证据不完整，禁止自动批准。",
            "revision_instructions": [],
        }
    else:
        try:
            messages = [
                SystemMessage(content=REVIEW_PROMPT),
                HumanMessage(content=user_input),
            ]
            llm_result = llm_gateway.invoke_structured(
                messages=messages,
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
            review = llm_result.output.model_dump(mode="python")
        except LLMGatewayError as exc:
            error = require_agent_fallback(state, exc.error)
            llm_result = exc
            review = {
                "decision": ReviewDecision.HUMAN_REVIEW.value,
                "passed": False,
                "hallucination_score": 0.3 if evidence else 0.5,
                "issues": [{
                    "code": "evidence_gap",
                    "severity": "high",
                    "resource_type": None,
                    "knowledge_point": None,
                    "description": "审核能力暂不可用，无法安全完成自动审核",
                }],
                "difficulty_match": False,
                "coverage_rate": 0.8,
                "suggestion": "",
                "revision_instructions": [],
            }

    review = _decorate_review_items(
        review,
        run_id=node_input.run_id,
        generation_attempt=node_input.generation_attempt,
    )
    instructions_valid = revision_instructions_are_valid(
        review.get("revision_instructions", []),
        [resource.resource_type for resource in resources],
    )
    decision = (
        ReviewDecision.HUMAN_REVIEW
        if error
        else decide_review(
            review,
            valid_source_refs=not invalid_source_refs,
            valid_revision_instructions=instructions_valid,
        )
    )

    review.update({
        "passed": decision == ReviewDecision.APPROVE,
        "decision": decision.value,
        "status": decision.value,
        "review_ids": review_ids,
        "revision_count": node_input.revision_count,
    })
    status = StepStatus.DEGRADED if error else StepStatus.SUCCESS
    NodeResult[ReviewerOutput](
        status=status,
        output=ReviewerOutput(review_result=review),
        error=error,
    )
    trace_item = build_trace_item(
        state,
        agent_name="reviewer",
        action="审核纠偏",
        status=status,
        input_summary=f"资源数：{len(resources)}；证据数：{len(evidence)}；生成轮次：{node_input.generation_attempt}",
        output_summary=f"决策：{decision.value}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
        decision_reason=review.get("suggestion", "根据知识库证据、事实一致性、覆盖率和难度匹配给出审核结论。"),
        evidence_refs=[item.evidence_id for item in evidence[:5]],
        resource_ids=[resource.resource_id for resource in resources],
        review_ids=list(review_ids.values()),
        error=error,
        attempt=node_input.generation_attempt,
        step_context=step_context,
        llm_metadata=llm_result.trace_metadata() if llm_result else None,
    )

    return {
        "review_result": review,
        "current_node": "reviewer",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
    }
