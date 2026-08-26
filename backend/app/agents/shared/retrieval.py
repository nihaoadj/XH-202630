"""Knowledge retrieval Agent backed by the validated evidence boundary.

The injected backend performs hybrid retrieval/reranking; this node still owns
the immutable KB/Chunk/hash validation before candidates become Evidence DTOs.
"""

from app.agents.resource_workflows.learning_documents.state import AgentState
from app.core.retrieval.retriever import EvidenceRetriever, retrieval_policy_from_settings
from app.core.security.errors import ErrorCode
from app.core.retrieval.knowledge_base import load_knowledge_base_manifest
from app.models.shared.agent_contracts import (
    NodeResult,
    RetrieverInput,
    RetrieverOutput,
    build_trace_item,
    make_error_info,
    require_agent_fallback,
    start_step,
)
from app.models.knowledge.knowledge import RetrievalRequest, RetrievalStatus
from app.models.shared.workflow import StepStatus


def _node_descriptor(node_id: str) -> tuple[str, list[str]]:
    """Resolve a human-searchable node descriptor from the frozen manifest."""
    try:
        nodes = load_knowledge_base_manifest().get("skill_nodes", [])
    except Exception:
        nodes = []
    for node in nodes:
        if isinstance(node, dict) and node.get("node_id") == node_id:
            return (
                str(node.get("name") or node_id),
                [str(item) for item in node.get("knowledge_points", []) if str(item).strip()],
            )
    return node_id, []


def _queries(node_input: RetrieverInput) -> tuple[list[str], dict[str, str]]:
    weak_points = node_input.diagnosis.get("weak_points", [])
    values = [node_input.topic]
    query_node_ids: dict[str, str] = {}
    target_nodes = list(dict.fromkeys(node_input.target_skill_nodes[:3]))
    if target_nodes:
        for node_id in target_nodes:
            name, points = _node_descriptor(node_id)
            query = " ".join([node_input.topic, name, *points]).strip()
            if query:
                values.append(query)
                query_node_ids[query] = node_id
    else:
        values.extend(f"{node_input.topic} {point}" for point in weak_points[:2])
    queries = list(dict.fromkeys(value.strip() for value in values if value.strip()))
    return queries, {query: node_id for query, node_id in query_node_ids.items() if query in queries}


def retrieve_node(
    state: AgentState,
    *,
    evidence_retriever: EvidenceRetriever,
) -> dict:
    """Resolve hybrid/reranked hits into immutable, KB-scoped Evidence DTOs."""

    step_context = start_step(state)
    node_input = RetrieverInput.model_validate(state)
    knowledge_base_id = node_input.knowledge_base_id or str(
        load_knowledge_base_manifest()["knowledge_base_id"]
    )
    queries, query_node_ids = _queries(node_input)
    configured_top_k = node_input.constraints.get("retrieval_top_k")
    top_k_override = (
        min(10, max(1, configured_top_k))
        if isinstance(configured_top_k, int) and not isinstance(configured_top_k, bool)
        else None
    )
    policy = retrieval_policy_from_settings(
        evidence_retriever.settings,
        top_k_override=top_k_override,
    )
    request = RetrievalRequest(
        run_id=node_input.run_id,
        step_id=step_context["step_id"],
        knowledge_base_id=knowledge_base_id,
        queries=queries,
        query_node_ids=query_node_ids,
        policy=policy,
    )
    batch = evidence_retriever.retrieve(request)

    error = batch.error
    if batch.status == RetrievalStatus.RETRIEVAL_ERROR and error is not None:
        error = require_agent_fallback(state, error)
    if batch.status == RetrievalStatus.AVAILABLE and batch.partial_failure_count:
        error = require_agent_fallback(
            state,
            make_error_info(
                ErrorCode.RETRIEVAL_UPSTREAM_UNAVAILABLE,
                source="retriever",
                category="retrieval",
                retryable=True,
                safe_detail="queries:partial_failure",
            ),
        )
    status = StepStatus.DEGRADED if error else StepStatus.SUCCESS
    output = RetrieverOutput(
        retrieved_evidence=batch.evidence,
        node_evidence_map=batch.node_evidence_map,
        retrieval_status=batch.status,
        retrieval_config_hash=batch.config_hash,
        retrieval_query_hashes=batch.query_hashes,
        retrieval_candidate_count=batch.candidate_count,
        retrieval_dropped_candidate_count=batch.dropped_candidate_count,
        retrieval_partial_failure_count=batch.partial_failure_count,
    )
    NodeResult[RetrieverOutput](status=status, output=output, error=error)

    trace_item = build_trace_item(
        state,
        agent_name="retriever",
        action="混合检索、精排与可信证据校验",
        status=status,
        input_summary=(
            f"知识库：{knowledge_base_id}；查询数：{batch.query_count}；"
            f"top_k：{policy.top_k_per_query}"
        ),
        output_summary=(
            f"混合候选 {batch.candidate_count} 条；有效证据 {len(batch.evidence)} 条；"
            f"状态：{batch.status.value}"
        ),
        decision_reason=(
            "候选先经向量/BM25 融合与可选 CrossEncoder 精排，再经知识库边界、"
            "SQL 历史版本和内容哈希校验后成为证据。"
        ),
        evidence_refs=[item.evidence_id for item in batch.evidence],
        error=error,
        step_context=step_context,
        retrieval_metadata={
            "retrieval_status": batch.status.value,
            "retrieval_config_hash": batch.config_hash,
            "retrieval_query_hashes": batch.query_hashes,
            "retrieval_candidate_count": batch.candidate_count,
            "retrieval_dropped_candidate_count": batch.dropped_candidate_count,
            "retrieval_partial_failure_count": batch.partial_failure_count,
            "retrieval_query_count": batch.query_count,
            "retrieval_evidence_count": len(batch.evidence),
            "retrieval_dropped_count": batch.dropped_candidate_count,
            "retrieval_profile": batch.retrieval_profile,
        },
    )
    return {
        "knowledge_base_id": knowledge_base_id,
        "retrieved_evidence": batch.evidence,
        "node_evidence_map": batch.node_evidence_map,
        "retrieved_chunks": [],
        "retrieval_status": batch.status.value,
        "retrieval_config_hash": batch.config_hash,
        "retrieval_query_hashes": batch.query_hashes,
        "retrieval_candidate_count": batch.candidate_count,
        "retrieval_dropped_candidate_count": batch.dropped_candidate_count,
        "retrieval_partial_failure_count": batch.partial_failure_count,
        "current_node": "retriever",
        "trace": [trace_item],
        "errors": [error.model_dump(mode="json")] if error else [],
    }
