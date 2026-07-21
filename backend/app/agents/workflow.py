from langgraph.graph import StateGraph, END

from app.agents.state import AgentState
from app.agents.diagnosis import diagnose_node
from app.agents.retriever import retrieve_node
from app.agents.generator import generate_node
from app.agents.reviewer import review_node


def decide_next(state: AgentState) -> str:
    """决策函数：根据审核结果决定下一步"""
    review = state.get("review_result", {})
    iteration = state.get("iteration", 0)

    if iteration >= 2:
        return "decide"

    if review.get("passed", False) and review.get("hallucination_score", 1.0) < 0.2:
        return "decide"

    return "generate"


def decide_node(state: AgentState) -> dict:
    """决策 Agent：整合结果并输出最终决策"""
    review = state.get("review_result", {})
    if review.get("passed", False):
        decision = "通过"
    else:
        decision = "带风险通过（需人工复核）"

    trace_item = {
        "agent_name": "supervisor",
        "action": "协同决策",
        "output_summary": f"最终决策：{decision}",
    }
    return {
        "final_decision": decision,
        "trace": [trace_item],
    }


def build_workflow():
    """构建 LangGraph 多智能体工作流"""
    workflow = StateGraph(AgentState)

    workflow.add_node("diagnose", diagnose_node)
    workflow.add_node("retrieve", retrieve_node)
    workflow.add_node("generate", generate_node)
    workflow.add_node("review", review_node)
    workflow.add_node("decide", decide_node)

    workflow.set_entry_point("diagnose")
    workflow.add_edge("diagnose", "retrieve")
    workflow.add_edge("retrieve", "generate")
    workflow.add_edge("generate", "review")
    workflow.add_conditional_edges(
        "review",
        decide_next,
        {"generate": "generate", "decide": "decide"},
    )
    workflow.add_edge("decide", END)

    return workflow.compile()
