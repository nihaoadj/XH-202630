"""Knowledge retrieval Agent backed by the validated P0-03 evidence boundary."""

from app.agents.state import AgentState
from app.core.evidence_retriever import (
    EvidenceRetriever,
    retrieval_policy_from_settings,
)
from app.core.errors import ErrorCode
from app.core.knowledge_base import load_knowledge_base_manifest
from app.models.agent_contracts import (
    NodeResult,
    RetrieverInput,
    RetrieverOutput,
    build_trace_item,
    make_error_info,
    require_agent_fallback,
    start_step,
)
from app.models.knowledge import RetrievalRequest, RetrievalStatus
from app.models.workflow import StepStatus


def _queries(node_input: RetrieverInput) -> list[str]:
    weak_points = node_input.diagnosis.get("weak_points", [])
    values = [node_input.topic]
    values.extend(
        f"{node_input.topic} {node}"
        for node in node_input.target_skill_nodes[:3]
    )
    values.extend(
        f"{node_input.topic} {point}"
        for point in weak_points[:2]
    )
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def retrieve_node(
    state: AgentState,
    *,
    evidence_retriever: EvidenceRetriever,
) -> dict:
    """Resolve vector hits into immutable, KB-scoped Evidence DTOs."""

    step_context = start_step(state)
    node_input = RetrieverInput.model_validate(state)
    knowledge_base_id = node_input.knowledge_base_id or str(
        load_knowledge_base_manifest()["knowledge_base_id"]
    )
    queries = _queries(node_input)
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
        action="知识证据检索",
        status=status,
        input_summary=(
            f"知识库：{knowledge_base_id}；查询数：{batch.query_count}；"
            f"top_k：{policy.top_k_per_query}"
        ),
        output_summary=(
            f"候选 {batch.candidate_count} 条；有效证据 {len(batch.evidence)} 条；"
            f"状态：{batch.status.value}"
        ),
        decision_reason="所有向量候选均经知识库边界、SQL 历史版本和内容哈希校验后才能成为证据。",
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
        },
    )
    return {
        "knowledge_base_id": knowledge_base_id,
        "retrieved_evidence": batch.evidence,
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
