import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.llm import get_llm


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


def review_node(state: AgentState) -> AgentState:
    """审核纠偏 Agent：事实核查、幻觉检测、难度匹配"""
    resources = state.get("generated_resources", [])
    chunks = state.get("retrieved_chunks", [])

    context = "\n\n".join([f"[片段 {i+1}] {c['content']}" for i, c in enumerate(chunks[:5])])
    resource_text = "\n\n".join(
        [f"[{r.resource_type}] 难度：{r.difficulty}\n{r.content_text or ''}" for r in resources]
    )

    user_input = f"""
专业知识片段：
{context}

待审核资源：
{resource_text}
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

    trace_item = {
        "agent_name": "reviewer",
        "action": "审核纠偏",
        "input_summary": f"资源数：{len(resources)}；证据片段数：{len(chunks)}",
        "output_summary": f"通过：{review.get('passed', False)}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
        "decision_reason": review.get("suggestion", "根据知识库证据、事实一致性、覆盖率和难度匹配给出审核结论。"),
        "evidence_refs": [c.get("source", "unknown") for c in chunks[:5]],
        "status": "degraded" if fallback_code else "success",
        "error_code": fallback_code,
    }

    return {
        "review_result": review,
        "trace": [trace_item],
    }
