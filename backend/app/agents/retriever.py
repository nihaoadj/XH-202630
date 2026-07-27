from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
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
    fallback_code = None

    for q in queries:
        try:
            results = similarity_search(q, top_k=3)
        except Exception:
            fallback_code = require_degraded_generation(ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE)
            results = []
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
        "action": "知识库检索",
        "input_summary": f"检索查询：{queries}",
        "output_summary": f"召回 {len(retrieved)} 条知识片段，最高相似度 {retrieved[0]['score'] if retrieved else 0:.3f}",
        "decision_reason": "围绕学习主题和前两个薄弱知识点扩展检索，优先为后续生成提供可溯源证据。",
        "evidence_refs": [item["source"] for item in retrieved[:5]],
        "status": "degraded" if fallback_code else "success",
        "error_code": fallback_code,
    }

    return {
        "retrieved_chunks": retrieved,
        "trace": [trace_item],
    }
