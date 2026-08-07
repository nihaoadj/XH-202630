from app.agents.state import AgentState
from app.config import get_settings
from app.core.errors import ErrorCode, require_degraded_generation
from app.core.reranker import build_rerank_query, mark_rerank_fallback, rerank_documents
from app.core.vector_store import hybrid_search
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
    settings = get_settings()
    candidate_limit = max(top_k, settings.rerank_candidate_k)
    per_query_k = max(top_k, min(settings.rerank_per_query_k, candidate_limit))
    candidates_by_id = {}
    fallback_code = None

    for q in queries:
        try:
            results = hybrid_search(q, top_k=per_query_k, knowledge_base_id=knowledge_base_id)
        except Exception:
            fallback_code = require_degraded_generation(ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE)
            results = []
        for doc, score in results:
            key = doc.metadata.get("chunk_id") or doc.page_content[:100]
            existing = candidates_by_id.get(key)
            matched_queries = list(
                dict.fromkeys([
                    *((existing[0].metadata.get("matched_queries", [])) if existing else []),
                    q,
                ])
            )
            if existing is not None and float(existing[1]) >= float(score):
                existing[0].metadata["matched_queries"] = matched_queries
                continue
            doc.metadata["matched_queries"] = matched_queries
            doc.metadata["retrieval_query"] = q
            candidates_by_id[key] = (doc, float(score))

    candidates = sorted(candidates_by_id.values(), key=lambda item: item[1], reverse=True)
    candidates = candidates[:candidate_limit]
    rerank_query = build_rerank_query(
        topic,
        target_skill_nodes=node_input.target_skill_nodes,
        weak_points=weak_points,
        difficulty=state.get("difficulty_preference"),
    )
    if candidates:
        try:
            final_results = rerank_documents(rerank_query, candidates, top_k=top_k)
        except Exception:
            final_results = mark_rerank_fallback(candidates, top_k, "unavailable")
    else:
        final_results = []

    retrieved = []
    for rank, (doc, score) in enumerate(final_results, start=1):
        retrieved.append({
            "content": doc.page_content,
            "knowledge_base_id": doc.metadata.get("knowledge_base_id"),
            "document_id": doc.metadata.get("document_id"),
            "chunk_id": doc.metadata.get("chunk_id"),
            "title": doc.metadata.get("title"),
            "source": doc.metadata.get("source_path", "unknown"),
            "knowledge_points": doc.metadata.get("knowledge_points", []),
            "score": float(score),
            "retrieval_method": doc.metadata.get("retrieval_method", "hybrid_rrf"),
            "retrieval_channels": doc.metadata.get("retrieval_channels", []),
            "vector_rank": doc.metadata.get("vector_rank"),
            "vector_score": doc.metadata.get("vector_score"),
            "lexical_rank": doc.metadata.get("lexical_rank"),
            "lexical_score": doc.metadata.get("lexical_score"),
            "hybrid_rank": doc.metadata.get("hybrid_rank"),
            "hybrid_score": doc.metadata.get("hybrid_score"),
            "rerank_status": doc.metadata.get("rerank_status"),
            "rerank_rank": doc.metadata.get("rerank_rank"),
            "rerank_raw_score": doc.metadata.get("rerank_raw_score"),
            "rerank_score": doc.metadata.get("rerank_score"),
            "reranker_model": doc.metadata.get("reranker_model"),
            "rerank_query_hash": doc.metadata.get("rerank_query_hash"),
            "rerank_latency_ms": doc.metadata.get("rerank_latency_ms"),
            "rerank_candidate_count": doc.metadata.get("rerank_candidate_count"),
            "final_score": doc.metadata.get("final_score", float(score)),
            "matched_queries": doc.metadata.get("matched_queries", []),
            "retrieval_query": doc.metadata.get("retrieval_query"),
            "rank": rank,
        })

    retrieval_status = "error" if fallback_code and not retrieved else "available" if retrieved else "no_hit"
    rerank_status = (
        retrieved[0].get("rerank_status") if retrieved else "not_run"
    )
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
        output_summary=(
            f"混合候选 {len(candidates)} 条，精排后保留 {len(retrieved)} 条；"
            f"检索状态：{retrieval_status}；精排状态：{rerank_status}"
        ),
        decision_reason="围绕学习主题、目标能力节点和薄弱知识点扩展查询，先融合 BM25 与向量召回，再使用 CrossEncoder 精排和来源多样性控制。",
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
