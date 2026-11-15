"""Freeze the optional Claim evidence retrieval policy from settings.

A Run keeps this object for its whole lifetime.  Changing ``.env`` afterwards
must not change an already-created Run, so every model, prompt, schema and
budget input is captured here and re-validated when the workflow reads it back.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.agents.resource_workflows.learning_documents.claim_evidence_retrieval.prompts import (
    query_prompt_hash,
    query_schema_hash,
    rejudge_prompt_hash,
    rejudge_schema_hash,
)
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    ClaimEvidenceRetrievalSnapshotV1,
)
from app.models.shared.persistence import canonical_hash


PRIVATE_FIELDS = frozenset({
    "claim_evidence_retrieval_policy", "claim_evidence_retrieval_policy_hash",
})


def _gateway_identity(gateway) -> tuple[str, str, str]:
    transport = getattr(gateway, "transport", gateway)
    settings = getattr(transport, "settings", None)
    base_url = str(getattr(settings, "llm_base_url", "offline")).rstrip("/")
    return (
        str(getattr(transport, "model_name", "") or ""),
        canonical_hash({"endpoint": base_url}),
        str(getattr(settings, "llm_thinking_mode", "")),
    )


def retrieval_fingerprint(settings) -> str:
    """Stable KB-independent retrieval fingerprint, frozen at job creation.

    The run-specific ``retrieval_config_hash`` is only produced once a retrieval
    executes, so the frozen contract records the deployment-level policy: model,
    rerank and strategy versions.  A later change to any of them cannot alter an
    already-created Run.
    """

    return canonical_hash({
        "embedding_model": str(getattr(settings, "embedding_model", "")),
        "rerank_enabled": bool(getattr(settings, "rerank_enabled", False)),
        "rerank_model": str(getattr(settings, "rerank_model", "")),
        "rerank_per_query_k": int(getattr(settings, "rerank_per_query_k", 0) or 0),
        "top_k": int(getattr(settings, "retrieval_top_k_default", 0) or 0),
        "max_queries": int(getattr(settings, "retrieval_max_queries", 0) or 0),
        "max_evidence": int(getattr(settings, "retrieval_max_evidence", 0) or 0),
        "min_score": float(getattr(settings, "retrieval_min_normalized_score", 0.0) or 0.0),
        "excerpt_chars": int(getattr(settings, "claim_evidence_retrieval_excerpt_chars", 0) or 0),
        "excerpt_structural_cap": int(
            getattr(settings, "claim_evidence_retrieval_excerpt_structural_cap", 0) or 0
        ),
        "excerpt_strategy": "claim_window_v1",
    })


def freeze_policy(
    settings,
    gateway,
    *,
    knowledge_base_id: str,
    created_at: datetime | None = None,
) -> ClaimEvidenceRetrievalPolicyV1:
    model_name, endpoint_hash, thinking = _gateway_identity(gateway)
    base = gateway.options_for("claim_evidence_query", temperature=0.0)
    return ClaimEvidenceRetrievalPolicyV1(
        max_sessions_per_resource_version=1,
        query_batch_claims=settings.claim_evidence_retrieval_query_batch_claims,
        rejudge_batch_claims=settings.claim_evidence_retrieval_rejudge_batch_claims,
        queries_per_claim=settings.claim_evidence_retrieval_queries_per_claim,
        max_queries_per_claim=settings.claim_evidence_retrieval_max_queries_per_claim,
        max_queries=settings.claim_evidence_retrieval_max_queries,
        queries_per_request=settings.claim_evidence_retrieval_queries_per_request,
        max_new_excerpts_per_resource=settings.claim_evidence_retrieval_max_new_excerpts_per_resource,
        max_new_excerpts=settings.claim_evidence_retrieval_max_new_excerpts,
        max_logical_calls=settings.claim_evidence_retrieval_max_logical_calls,
        max_attempts=settings.claim_evidence_retrieval_max_attempts,
        attempts_per_call=settings.claim_evidence_retrieval_attempts_per_call,
        query_input_cap=settings.claim_evidence_retrieval_query_input_cap,
        query_output_cap=settings.claim_evidence_retrieval_query_output_cap,
        rejudge_input_cap=settings.claim_evidence_retrieval_rejudge_input_cap,
        rejudge_output_cap=settings.claim_evidence_retrieval_rejudge_output_cap,
        rejudge_truncated_output_cap=settings.claim_evidence_retrieval_rejudge_truncated_output_cap,
        max_estimated_tokens=settings.claim_evidence_retrieval_max_estimated_tokens,
        attempt_timeout_seconds=min(
            settings.claim_evidence_retrieval_attempt_timeout_seconds,
            float(base.request_timeout_seconds),
        ),
        retrieval_timeout_seconds=settings.claim_evidence_retrieval_retrieval_timeout_seconds,
        max_wall_seconds=settings.claim_evidence_retrieval_max_wall_seconds,
        downstream_reserve_seconds=settings.claim_evidence_retrieval_downstream_reserve_seconds,
        excerpt_chars=settings.claim_evidence_retrieval_excerpt_chars,
        excerpt_structural_cap=settings.claim_evidence_retrieval_excerpt_structural_cap,
        query_prompt_hash=query_prompt_hash(),
        query_schema_hash=query_schema_hash(),
        rejudge_prompt_hash=rejudge_prompt_hash(),
        rejudge_schema_hash=rejudge_schema_hash(),
        model_name=model_name,
        endpoint_hash=endpoint_hash,
        thinking_mode=thinking,
        embedding_model=str(getattr(settings, "embedding_model", "")),
        rerank_model=str(getattr(settings, "rerank_model", "")),
        gateway_options={
            "max_attempts": 1,
            "allow_schema_repair": False,
            "allow_text_fallback": False,
            "structured_output_mode": base.structured_output_mode.value,
            "temperature": 0.0,
        },
        knowledge_base_id=knowledge_base_id,
        retrieval_config_hash=retrieval_fingerprint(settings)[:64],
        created_at=created_at or datetime.now(timezone.utc),
    )


def freeze_snapshot(
    *,
    request,
    settings,
    gateway,
    knowledge_base_id: str,
    claim_extraction_mode: str | None = None,
    claim_extraction_policy_hash: str | None = None,
) -> dict[str, Any]:
    """Return the private snapshot fields, or ``{}`` when the switch is off."""

    if not getattr(request, "include_claim_evidence_retrieval", False):
        return {}
    if not request.include_claim_check or not request.include_review:
        raise ValueError("Claim evidence retrieval requires review and Claim audit")
    policy = freeze_policy(
        settings, gateway, knowledge_base_id=knowledge_base_id,
    )
    snapshot = ClaimEvidenceRetrievalSnapshotV1(
        enabled=True,
        policy=policy,
        policy_hash=policy.policy_hash,
        claim_extraction_mode=claim_extraction_mode,
        claim_extraction_policy_hash=claim_extraction_policy_hash,
    )
    return {
        "claim_evidence_retrieval_policy": policy.model_dump(mode="json"),
        "claim_evidence_retrieval_policy_hash": snapshot.policy_hash,
    }


def policy_from_state(state: dict[str, Any]) -> ClaimEvidenceRetrievalPolicyV1 | None:
    """Read the frozen policy and reject partial or drifted snapshots."""

    raw = state.get("claim_evidence_retrieval_policy")
    digest = state.get("claim_evidence_retrieval_policy_hash")
    if raw is None and digest is None:
        return None
    if not isinstance(raw, dict) or not isinstance(digest, str):
        raise ValueError("Claim evidence retrieval policy is incomplete")
    policy = ClaimEvidenceRetrievalPolicyV1.model_validate(raw)
    if policy.policy_hash != digest:
        raise ValueError("Claim evidence retrieval policy hash mismatch")
    return policy


__all__ = [
    "PRIVATE_FIELDS",
    "freeze_policy",
    "freeze_snapshot",
    "policy_from_state",
    "retrieval_fingerprint",
]
