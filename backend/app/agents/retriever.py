from app.agents.state import AgentState
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.vector_store import similarity_search
from app.models.agent_contracts import (
    NodeResult,
    RetrieverInput,
    RetrieverOutput,
    build_trace_item,
    make_error_info,
    start_step,
)
from app.models.workflow import StepStatus


def retrieve_node(state: AgentState) -> dict:
    """知识检索 Agent：基于诊断结果与学习主题召回领域知识片段"""
    step_context = start_step(state)
    node_input = RetrieverInput.model_validate(state)
    topic = node_input.topic
    knowledge_base_id = node_input.knowledge_base_id
    diagnosis = node_input.diagnosis
    weak_points = diagnosis.get("weak_points", [])

    # 构造查询：主题 + 目标节点 + 盲区，去重并保留请求顺序。
    queries = [topic]
    queries.extend(f"{topic} {node}" for node in node_input.target_skill_nodes[:3])
    queries.extend(f"{topic} {point}" for point in weak_points[:2])
    queries = list(dict.fromkeys(queries))
    configured_top_k = node_input.constraints.get("retrieval_top_k", 3)
    top_k = configured_top_k if isinstance(configured_top_k, int) else 3
    top_k = min(10, max(1, top_k))
    retrieved = []
    seen = set()
    fallback_code = None

    for q in queries:
        try:
            results = similarity_search(q, top_k=top_k, knowledge_base_id=knowledge_base_id)
        except Exception:
            fallback_code = require_degraded_generation(ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE)
            results = []
        for rank, (doc, score) in enumerate(results, start=1):
            key = doc.metadata.get("chunk_id") or doc.page_content[:100]
            if key in seen:
                continue
            seen.add(key)
            retrieved.append({
                "content": doc.page_content,
                "knowledge_base_id": doc.metadata.get("knowledge_base_id"),
                "document_id": doc.metadata.get("document_id"),
                "chunk_id": doc.metadata.get("chunk_id"),
                "title": doc.metadata.get("title"),
                "source": doc.metadata.get("source_path", "unknown"),
                "knowledge_points": doc.metadata.get("knowledge_points", []),
                "score": float(score),
                "retrieval_query": q,
                "rank": rank,
            })

    retrieval_status = "error" if fallback_code and not retrieved else "available" if retrieved else "no_hit"
    status = StepStatus.DEGRADED if fallback_code else StepStatus.SUCCESS
    error = (
        make_error_info(fallback_code, source="retriever")
        if fallback_code
        else None
    )
    NodeResult[RetrieverOutput](
        status=status,
        output=RetrieverOutput(
            retrieved_chunks=retrieved,
            retrieval_status=retrieval_status,
        ),
        error=error,
    )
    trace_item = build_trace_item(
        state,
        agent_name="retriever",
        action="知识库检索",
        status=status,
        input_summary=f"知识库：{knowledge_base_id or '默认'}；检索查询：{queries}",
        output_summary=f"召回 {len(retrieved)} 条知识片段；状态：{retrieval_status}",
        decision_reason="围绕学习主题、目标能力节点和薄弱知识点扩展检索，为后续生成提供可溯源证据。",
        evidence_refs=[item.get("chunk_id") or item["source"] for item in retrieved[:5]],
        error=error,
        step_context=step_context,
    )

    return {
        "retrieved_chunks": retrieved,
        "retrieval_status": retrieval_status,
        "current_node": "retriever",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
    }
