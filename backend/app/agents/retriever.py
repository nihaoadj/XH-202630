from app.agents.state import AgentState
from app.core.vector_store import similarity_search


def retrieve_node(state: AgentState) -> AgentState:
    """知识检索 Agent：基于诊断结果与学习主题召回领域知识片段"""
    topic = state["topic"]
    diagnosis = state.get("diagnosis", {})
    weak_points = diagnosis.get("weak_points", [])

    # 构造查询：主题 + 盲区
    queries = [topic] + [f"{topic} {wp}" for wp in weak_points[:2]]
    retrieved = []
    seen = set()

    for q in queries:
        results = similarity_search(q, top_k=3)
        for doc, score in results:
            key = doc.page_content[:100]
            if key in seen:
                continue
            seen.add(key)
            retrieved.append({
                "content": doc.page_content,
                "source": doc.metadata.get("source", "unknown"),
                "score": float(score),
            })

    trace_item = {
        "agent_name": "retriever",
        "action": "知识检索",
        "output_summary": f"召回 {len(retrieved)} 条知识片段，最高相似度 {retrieved[0]['score'] if retrieved else 0:.3f}",
    }

    return {
        "retrieved_chunks": retrieved,
        "trace": [trace_item],
    }
