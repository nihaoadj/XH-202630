"""Deterministic query planning: batching, validation, fallback and fairness.

No model or database call happens here.  The node passes an ``invoke`` callable
so the same pure planning can be tested without a gateway.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Sequence

from app.models.reviews.claim_evidence_retrieval import (
    MAX_CLAIM_QUERIES,
    MAX_QUERY_CHARS,
    ClaimEvidenceRetrievalPolicyV1,
    ClaimQueryBatchOutputV1,
    batch_id_for,
)
from app.models.reviews.claims import ClaimRecord
from app.models.shared.persistence import canonical_hash


_CONDITION = re.compile(r"[0-9]+(?:\.[0-9]+)?\s*(?:%|个|条|次|秒|分钟|小时|天|年|MB|GB|KB|ms|s)?")
_FALLBACK_STRIP = re.compile(r"[“”\"'`《》()（）\[\]【】]")


def estimate_tokens(text: str) -> int:
    """Conservative character bound; it is an estimate, never a bill."""

    ascii_chars = sum(1 for char in text if ord(char) < 128)
    other = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars * 0.3 + other * 0.7))


@dataclass(frozen=True)
class QueryBatch:
    batch_id: str
    ordinal: int
    claim_ids: tuple[str, ...]
    input_hash: str
    payload: dict
    estimated_input_tokens: int

    @property
    def messages_payload(self) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


@dataclass(frozen=True)
class QueryPlan:
    batches: tuple[QueryBatch, ...]
    oversize_claim_ids: tuple[str, ...] = ()


def _payload_for(claims: Sequence[ClaimRecord], *, policy, knowledge_base_id: str) -> dict:
    return {
        "knowledge_base_id": knowledge_base_id,
        "queries_per_claim": policy.queries_per_claim,
        "max_queries_per_claim": policy.max_queries_per_claim,
        "claims": [
            {
                "claim_id": item.claim_id,
                "claim_text": item.claim_text,
                "source_text": item.source_text[:600],
                "knowledge_point_id": item.knowledge_point_id,
            }
            for item in claims
        ],
    }


def build_query_batches(
    claims: Sequence[ClaimRecord],
    *,
    session_id: str,
    policy: ClaimEvidenceRetrievalPolicyV1,
    knowledge_base_id: str,
) -> QueryPlan:
    """Split into stable batches; a single oversize Claim is reported, not cut."""

    ordered = list(claims)
    batches: list[QueryBatch] = []
    oversize: list[str] = []
    ordinal = 0

    def emit(group: Sequence[ClaimRecord]) -> None:
        nonlocal ordinal
        if not group:
            return
        payload = _payload_for(group, policy=policy, knowledge_base_id=knowledge_base_id)
        text = json.dumps(payload, ensure_ascii=False)
        if estimate_tokens(text) + policy.query_output_cap > (
            policy.query_input_cap + policy.query_output_cap
        ):
            if len(group) == 1:
                oversize.append(group[0].claim_id)
                return
            middle = len(group) // 2
            emit(group[:middle])
            emit(group[middle:])
            return
        input_hash = canonical_hash(payload)
        batch_id = batch_id_for(
            session_id=session_id, kind="query", ordinal=ordinal, input_hash=input_hash,
        )
        batches.append(QueryBatch(
            batch_id=batch_id,
            ordinal=ordinal,
            claim_ids=tuple(item.claim_id for item in group),
            input_hash=input_hash,
            payload={**payload, "batch_id": batch_id, "input_hash": input_hash},
            estimated_input_tokens=estimate_tokens(text),
        ))
        ordinal += 1

    for start in range(0, len(ordered), policy.query_batch_claims):
        emit(ordered[start:start + policy.query_batch_claims])
    return QueryPlan(batches=tuple(batches), oversize_claim_ids=tuple(oversize))


def validate_query_output(
    output: ClaimQueryBatchOutputV1,
    *,
    batch: QueryBatch,
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> dict[str, tuple[str, ...]]:
    """Reject omissions, extra claims, duplicates and over-long queries."""

    if output.batch_id != batch.batch_id:
        raise ValueError("query batch id mismatch")
    if output.input_hash != batch.input_hash:
        raise ValueError("query batch input hash mismatch")
    expected = set(batch.claim_ids)
    returned = [item.claim_id for item in output.items]
    if len(returned) != len(set(returned)):
        raise ValueError("query batch repeats a claim")
    if set(returned) != expected:
        raise ValueError("query batch claim set mismatch")
    result: dict[str, tuple[str, ...]] = {}
    for item in output.items:
        texts = [query.text.strip() for query in item.queries]
        if not 1 <= len(texts) <= policy.max_queries_per_claim:
            raise ValueError("query count outside the frozen range")
        if len(texts) != len(set(texts)):
            raise ValueError("duplicate query text for one claim")
        if any(not text or len(text) > MAX_QUERY_CHARS for text in texts):
            raise ValueError("query text outside the frozen length")
        result[item.claim_id] = tuple(texts)
    return result


def deterministic_queries(
    claim: ClaimRecord,
    *,
    max_queries: int = 2,
) -> tuple[str, ...]:
    """Bounded verbatim fallback; never rewrites the claim into a conclusion."""

    text = _FALLBACK_STRIP.sub(" ", claim.claim_text or "").strip()
    if not text:
        return ()
    text = re.sub(r"\s+", " ", text)
    if len(text) <= MAX_QUERY_CHARS:
        return (text,)
    numbers = [item.group(0).strip() for item in _CONDITION.finditer(text)]
    head = text[: MAX_QUERY_CHARS]
    head = head[: head.rfind("，") if "，" in head else len(head)]
    if not head.strip():
        return ()
    queries = [head.strip()]
    if numbers:
        tail = f"{head.strip()[:200]} {' '.join(dict.fromkeys(numbers))[:200]}".strip()
        if tail and tail != queries[0] and len(tail) <= MAX_QUERY_CHARS:
            queries.append(tail)
    return tuple(queries[:max_queries])


def assign_query_quota(
    queries_by_claim: dict[str, tuple[str, ...]],
    claim_order: Sequence[str],
    *,
    max_queries: int,
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...], dict[str, int]]:
    """Round-robin allocation so no early Claim starves the rest.

    Returns the selected queries, the claims that received nothing, and safe
    counts (requested/selected/dropped) for the session ledger.
    """

    selected: dict[str, list[str]] = {claim_id: [] for claim_id in claim_order}
    seen: set[str] = set()
    assigned = 0
    counts = {"requested": 0, "selected": 0, "dropped_duplicate": 0, "dropped_budget": 0}
    max_rounds = max((len(queries_by_claim.get(claim_id, ())) for claim_id in claim_order), default=0)
    for index in range(max_rounds):
        for claim_id in claim_order:
            values = queries_by_claim.get(claim_id, ())
            if index >= len(values):
                continue
            counts["requested"] += 1
            query = values[index]
            key = query.strip().casefold()
            if not key or key in seen:
                counts["dropped_duplicate"] += 1
                continue
            if assigned >= max_queries:
                counts["dropped_budget"] += 1
                continue
            seen.add(key)
            selected[claim_id].append(query)
            assigned += 1
            counts["selected"] += 1
    exhausted = tuple(
        claim_id for claim_id in claim_order if not selected.get(claim_id)
    )
    return (
        {claim_id: tuple(values) for claim_id, values in selected.items()},
        exhausted,
        counts,
    )


def collect_claim_queries(
    *,
    batches: Sequence[QueryBatch],
    outputs: dict[str, dict[str, tuple[str, ...]]],
    fallback_claim_ids: Iterable[str],
    claims: Sequence[ClaimRecord],
    policy: ClaimEvidenceRetrievalPolicyV1,
) -> tuple[dict[str, tuple[str, ...]], tuple[str, ...], dict[str, int]]:
    """Merge validated model output with the deterministic fallback."""

    by_id = {item.claim_id: item for item in claims}
    merged: dict[str, tuple[str, ...]] = {}
    for batch in batches:
        for claim_id, queries in outputs.get(batch.batch_id, {}).items():
            merged[claim_id] = tuple(queries[: policy.max_queries_per_claim])
    for claim_id in fallback_claim_ids:
        claim = by_id.get(claim_id)
        if claim is None:
            continue
        fallback = deterministic_queries(claim, max_queries=policy.queries_per_claim)
        if fallback:
            merged[claim_id] = fallback
    order = [item.claim_id for item in claims if item.claim_id in merged]
    return assign_query_quota(merged, order, max_queries=policy.max_queries)


def query_claim_map(
    selected: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Invert claim→queries into normalized query→claims for retrieval."""

    inverse: dict[str, list[str]] = {}
    for claim_id, queries in selected.items():
        for query in queries:
            inverse.setdefault(query.strip().casefold(), []).append(claim_id)
    return {query: tuple(dict.fromkeys(claims)) for query, claims in inverse.items()}


__all__ = [
    "QueryBatch",
    "QueryPlan",
    "assign_query_quota",
    "build_query_batches",
    "collect_claim_queries",
    "deterministic_queries",
    "estimate_tokens",
    "query_claim_map",
    "validate_query_output",
]
