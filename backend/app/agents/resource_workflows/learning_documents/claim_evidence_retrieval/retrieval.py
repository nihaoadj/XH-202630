"""Plan and select supplementary evidence without inventing a second retriever."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping, Sequence

from app.core.retrieval.retriever import EvidenceRetriever
from app.models.knowledge.knowledge import (
    EvidenceBatch,
    EvidenceItem,
    RetrievalPolicy,
    RetrievalRequest,
    RetrievalStatus,
)
from app.models.reviews.claim_evidence_retrieval import (
    ClaimEvidenceRetrievalPolicyV1,
    batch_id_for,
)
from app.models.shared.persistence import canonical_hash


@dataclass(frozen=True)
class RetrievalBatchPlan:
    batch_id: str
    ordinal: int
    queries: tuple[str, ...]
    claim_ids_by_query: Mapping[str, tuple[str, ...]]
    input_hash: str


@dataclass(frozen=True)
class EvidenceSelection:
    selected: tuple[EvidenceItem, ...]
    candidates: tuple[dict, ...]
    new_identity_total: int
    dropped_by_cap_total: int


def plan_retrieval_batches(
    selected: Mapping[str, tuple[str, ...]],
    *,
    session_id: str,
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> tuple[RetrievalBatchPlan, ...]:
    """Ordered query chunks with an explicit query→Claim mapping."""

    ordered: list[str] = []
    mapping: dict[str, list[str]] = {}
    for claim_id, queries in selected.items():
        for query in queries:
            key = query.strip()
            if key not in mapping:
                ordered.append(key)
            mapping.setdefault(key, [])
            if claim_id not in mapping[key]:
                mapping[key].append(claim_id)
    plans: list[RetrievalBatchPlan] = []
    size = max(1, policy.queries_per_request)
    for ordinal, start in enumerate(range(0, len(ordered), size)):
        chunk = tuple(ordered[start:start + size])
        if not chunk:
            continue
        payload = {
            "queries": list(chunk),
            "claims": {query: mapping[query] for query in chunk},
        }
        input_hash = canonical_hash(payload)
        plans.append(RetrievalBatchPlan(
            batch_id=batch_id_for(
                session_id=session_id, kind="retrieve", ordinal=ordinal, input_hash=input_hash,
            ),
            ordinal=ordinal,
            queries=chunk,
            claim_ids_by_query={query: tuple(mapping[query]) for query in chunk},
            input_hash=input_hash,
        ))
    return tuple(plans)


def supplementary_retrieval_policy(
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> RetrievalPolicy:
    """A bounded, explicit policy; the retriever keeps its own models.

    The supplement never changes the embedding or rerank model: it only narrows
    the query/excerpt envelope to the frozen numbers and selects the targeted
    excerpt strategy.  Legacy callers keep the default ``prefix`` policy.
    """

    return RetrievalPolicy(
        top_k_per_query=6,
        max_query_count=min(6, policy.queries_per_request),
        min_normalized_score=0.35,
        min_evidence_count=1,
        max_evidence_count=max(6, policy.max_new_excerpts_per_resource),
        max_excerpt_chars=policy.excerpt_chars,
        excerpt_strategy="claim_window_v1",
        excerpt_chars=policy.excerpt_chars,
        excerpt_structural_cap=policy.excerpt_structural_cap,
        distance_metric="cosine",
        query_strategy_version="deterministic-v1",
        ranking_strategy_version="normalized-score-v1",
    )


def run_retrieval_batch(
    retriever: EvidenceRetriever,
    *,
    run_id: str,
    step_id: str,
    knowledge_base_id: str,
    plan: RetrievalBatchPlan,
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> EvidenceBatch:
    request = RetrievalRequest(
        run_id=run_id,
        step_id=step_id,
        knowledge_base_id=knowledge_base_id,
        queries=list(plan.queries),
        policy=supplementary_retrieval_policy(policy),
    )
    return retriever.retrieve_with_deadline(
        request, timeout_seconds=policy.retrieval_timeout_seconds,
    )


def evidence_content_identity(item: EvidenceItem) -> tuple[str, str, str, str]:
    """New evidence means new content identity, not a new score or rank."""

    return (item.document_id, item.document_version, item.chunk_id, item.excerpt_hash)


def authorized_pool_identities(
    evidence: Iterable[EvidenceItem],
    *,
    authorized_evidence_ids: Iterable[str] = (),
) -> set[tuple[str, str, str, str]]:
    allowed = set(authorized_evidence_ids)
    return {
        evidence_content_identity(item)
        for item in evidence
        if not allowed or item.evidence_id in allowed
    }


def select_new_evidence(
    batches: Sequence[EvidenceBatch],
    *,
    claim_ids_by_query: Mapping[str, tuple[str, ...]],
    base_pool: set[tuple[str, str, str, str]],
    claim_order: Sequence[str],
    per_resource_cap: int,
    remaining_total: int,
) -> EvidenceSelection:
    """Fair, order-stable selection that never filters out counter-evidence."""

    candidates: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    by_claim: dict[str, list[EvidenceItem]] = {claim_id: [] for claim_id in claim_order}
    duplicates = 0
    for batch in batches:
        for item in batch.evidence:
            identity = evidence_content_identity(item)
            if identity in base_pool or identity in seen:
                duplicates += 1
                candidates.append({
                    "evidence_id": item.evidence_id,
                    "chunk_id": item.chunk_id,
                    "document_id": item.document_id,
                    "excerpt_hash": item.excerpt_hash,
                    "normalized_score": item.normalized_score,
                    "selected": False,
                    "reason": "duplicate_or_existing",
                })
                continue
            seen.add(identity)
            claims = claim_ids_by_query.get(item.query.strip(), ())
            for claim_id in claims:
                by_claim.setdefault(claim_id, []).append(item)
            candidates.append({
                "evidence_id": item.evidence_id,
                "chunk_id": item.chunk_id,
                "document_id": item.document_id,
                "excerpt_hash": item.excerpt_hash,
                "normalized_score": item.normalized_score,
                "claim_ids": list(claims),
                "selected": False,
                "reason": None,
            })
    selected: list[EvidenceItem] = []
    selected_ids: set[str] = set()
    cap = min(per_resource_cap, max(0, remaining_total))
    # Round-robin over claims: an early Claim cannot consume the whole quota.
    index = 0
    while len(selected) < cap:
        advanced = False
        for claim_id in claim_order:
            items = by_claim.get(claim_id) or []
            while index < len(items) and items[index].evidence_id in selected_ids:
                index += 1
            if index >= len(items):
                continue
            item = items[index]
            if len(selected) >= cap:
                break
            selected.append(item)
            selected_ids.add(item.evidence_id)
            advanced = True
        if not advanced:
            break
    for record in candidates:
        if record["evidence_id"] in selected_ids:
            record["selected"] = True
            record["reason"] = None
        elif record["reason"] is None:
            record["reason"] = "quota"
    return EvidenceSelection(
        selected=tuple(selected),
        candidates=tuple(candidates),
        new_identity_total=len(seen),
        dropped_by_cap_total=max(0, len(seen) - len(selected)),
    )


def merge_evidence_items(
    base: Sequence[EvidenceItem], extra: Sequence[EvidenceItem],
) -> list[EvidenceItem]:
    """Ordered union by evidence id; base order is preserved."""

    result: list[EvidenceItem] = []
    seen: set[str] = set()
    for item in [*base, *extra]:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        result.append(item)
    return result


__all__ = [
    "EvidenceSelection",
    "RetrievalBatchPlan",
    "authorized_pool_identities",
    "evidence_content_identity",
    "merge_evidence_items",
    "plan_retrieval_batches",
    "run_retrieval_batch",
    "select_new_evidence",
    "supplementary_retrieval_policy",
]
