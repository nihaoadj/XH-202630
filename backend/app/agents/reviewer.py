import json
import uuid
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.llm_gateway import LLMGateway, LLMGatewayError
from app.models.agent_contracts import (
    NodeResult,
    ReviewLLMOutput,
    ReviewerInput,
    ReviewerOutput,
    build_trace_item,
    require_agent_fallback,
    start_step,
)
from app.models.llm import LLMCallContext
from app.models.workflow import ReviewDecision, StepStatus


REVIEW_PROMPT = """你是一名严格的内容审核 Agent。请对以下学习资源进行审核，重点检查：
1. 是否存在与专业知识片段不符的事实错误（幻觉）。
2. 操作步骤是否符合行业规范。
3. 资源难度是否与学习者水平匹配。
4. 内容是否完整覆盖目标知识点。

请用 JSON 格式输出：
{
  "decision": "approve" | "revise" | "reject",
  "hallucination_score": float (0-1, 越高表示幻觉越严重),
  "issues": ["问题描述"],
  "difficulty_match": bool,
  "coverage_rate": float (0-1),
  "suggestion": "审核判断或改进建议",
  "revision_instructions": ["可执行的修改要求"]
}
不要包含额外解释。
"""


def review_node(
    state: AgentState,
    *,
    llm_gateway: LLMGateway,
) -> dict:
    """审核纠偏 Agent：事实核查、幻觉检测、难度匹配"""
    node_input = ReviewerInput.model_validate(state)
    resources = node_input.generated_resources
    chunks = node_input.retrieved_chunks
    step_context = start_step(state, attempt=node_input.generation_attempt)
    review_ids = {
        resource.resource_id: str(uuid.uuid4())
        for resource in resources
    }

    context = "\n\n".join([f"[片段 {i+1}] {c['content']}" for i, c in enumerate(chunks[:5])])
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
            "hallucination_score": 0.3 if chunks else 0.5,
            "issues": ["使用保底审核结果，建议补充知识库证据或配置 LLM 后复核"],
            "difficulty_match": False,
            "coverage_rate": 0.8,
            "suggestion": "",
            "revision_instructions": ["转人工复核，不得自动批准"],
        }

    if error:
        decision = ReviewDecision.HUMAN_REVIEW
    else:
        requested_decision = ReviewDecision(review["decision"])
        if requested_decision == ReviewDecision.REJECT:
            decision = ReviewDecision.REJECT
        elif (
            requested_decision == ReviewDecision.APPROVE
            and review["hallucination_score"] < 0.2
            and review["difficulty_match"]
            and review["coverage_rate"] >= 0.8
        ):
            decision = ReviewDecision.APPROVE
        else:
            decision = ReviewDecision.REVISE

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
        input_summary=f"资源数：{len(resources)}；证据片段数：{len(chunks)}；生成轮次：{node_input.generation_attempt}",
        output_summary=f"决策：{decision.value}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
        decision_reason=review.get("suggestion", "根据知识库证据、事实一致性、覆盖率和难度匹配给出审核结论。"),
        evidence_refs=[c.get("chunk_id") or c.get("source", "unknown") for c in chunks[:5]],
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
