import json
import uuid
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.llm import get_llm
from app.models.agent_contracts import (
    NodeResult,
    ReviewerInput,
    ReviewerOutput,
    build_trace_item,
    make_error_info,
    start_step,
)
from app.models.workflow import ReviewDecision, StepStatus


REVIEW_PROMPT = """你是一名严格的内容审核 Agent。请对以下学习资源进行审核，重点检查：
1. 是否存在与专业知识片段不符的事实错误（幻觉）。
2. 操作步骤是否符合行业规范。
3. 资源难度是否与学习者水平匹配。
4. 内容是否完整覆盖目标知识点。

请用 JSON 格式输出：
{
  "passed": bool,
  "hallucination_score": float (0-1, 越高表示幻觉越严重),
  "issues": ["问题描述"],
  "difficulty_match": bool,
  "coverage_rate": float (0-1),
  "suggestion": "改进建议"
}
不要包含额外解释。
"""


def review_node(state: AgentState) -> dict:
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
    fallback_code = None
    try:
        llm = get_llm()
        messages = [
            SystemMessage(content=REVIEW_PROMPT),
            HumanMessage(content=user_input),
        ]
        response = llm.invoke(messages)
        review = json.loads(response.content)
        if not isinstance(review, dict):
            raise ValueError("reviewer output must be an object")
    except Exception:
        fallback_code = require_degraded_generation(ErrorCode.LLM_UPSTREAM_UNAVAILABLE)
        review = {
            "passed": False,
            "hallucination_score": 0.3 if chunks else 0.5,
            "issues": ["使用保底审核结果，建议补充知识库证据或配置 LLM 后复核"],
            "difficulty_match": False,
            "coverage_rate": 0.8,
            "suggestion": "",
        }

    if fallback_code:
        decision = ReviewDecision.HUMAN_REVIEW
    else:
        requested_decision = review.get("decision")
        if requested_decision in {item.value for item in ReviewDecision}:
            decision = ReviewDecision(requested_decision)
        elif review.get("passed", False) and review.get("hallucination_score", 1.0) < 0.2:
            decision = ReviewDecision.APPROVE
        else:
            decision = ReviewDecision.REVISE

    review.update({
        "decision": decision.value,
        "status": decision.value,
        "review_ids": review_ids,
        "revision_count": node_input.revision_count,
    })
    status = StepStatus.DEGRADED if fallback_code else StepStatus.SUCCESS
    error = (
        make_error_info(
            fallback_code,
            source="reviewer",
            attempt=node_input.generation_attempt,
        )
        if fallback_code
        else None
    )
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
    )

    return {
        "review_result": review,
        "current_node": "reviewer",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
    }
