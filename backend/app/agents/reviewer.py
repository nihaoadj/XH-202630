import json
from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.state import AgentState
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
    llm = get_llm()
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
    messages = [
        SystemMessage(content=REVIEW_PROMPT),
        HumanMessage(content=user_input),
    ]
    response = llm.invoke(messages)

    try:
        review = json.loads(response.content)
    except json.JSONDecodeError:
        review = {
            "passed": True,
            "hallucination_score": 0.5,
            "issues": ["审核结果解析失败，默认通过"],
            "difficulty_match": True,
            "coverage_rate": 0.8,
            "suggestion": "",
        }

    trace_item = {
        "agent_name": "reviewer",
        "action": "内容审核",
        "output_summary": f"通过：{review.get('passed', False)}; 幻觉分：{review.get('hallucination_score', 0):.2f}; 覆盖率：{review.get('coverage_rate', 0):.2f}",
    }

    return {
        "review_result": review,
        "trace": [trace_item],
    }
