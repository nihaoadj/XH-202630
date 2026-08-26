"""CrossEncoder reranking for hybrid-retrieval candidates."""
from __future__ import annotations

from functools import lru_cache
import hashlib
import math
from threading import Lock
from time import perf_counter
from typing import Sequence

from langchain.schema import Document

from app.config import get_settings, resolve_backend_path


_RERANKER_LOAD_FAILURE_AT: float | None = None
_RERANKER_LOAD_RETRY_SECONDS = 60.0
_RERANKER_LOAD_LOCK = Lock()


@lru_cache(maxsize=1)
def _load_reranker():
    """Load one process-local CrossEncoder from the configured C-drive cache."""
    settings = get_settings()
    if not settings.rerank_enabled:
        raise RuntimeError("RERANK_DISABLED")

    import torch
    from sentence_transformers import CrossEncoder

    cache_dir = resolve_backend_path(settings.rerank_model_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    return CrossEncoder(
        settings.rerank_model,
        max_length=settings.rerank_max_length,
        device=settings.rerank_device,
        cache_dir=str(cache_dir),
        default_activation_function=torch.nn.Identity(),
    )


def get_reranker():
    """Load the model once and briefly back off after a failed cold load.

    Failed ``lru_cache`` calls are not cached. Without this guard, every query
    repeats the same network/model-load retry storm. The cooldown is bounded so
    a repaired cache or network is retried without restarting the process.
    """

    global _RERANKER_LOAD_FAILURE_AT
    # functools.lru_cache protects its mapping, but permits duplicate
    # concurrent cache misses.  Serializing only the cold-load section avoids
    # multiple CrossEncoder instances racing over the model cache when several
    # generation jobs reach retrieval at the same time.
    with _RERANKER_LOAD_LOCK:
        now = perf_counter()
        if (
            _RERANKER_LOAD_FAILURE_AT is not None
            and now - _RERANKER_LOAD_FAILURE_AT < _RERANKER_LOAD_RETRY_SECONDS
        ):
            get_reranker.last_cache_status = "failure_backoff"  # type: ignore[attr-defined]
            raise RuntimeError("RERANK_MODEL_LOAD_BACKOFF")
        before = _load_reranker.cache_info()
        try:
            model = _load_reranker()
        except Exception:
            _RERANKER_LOAD_FAILURE_AT = now
            get_reranker.last_cache_status = "load_failed"  # type: ignore[attr-defined]
            raise
        after = _load_reranker.cache_info()
        _RERANKER_LOAD_FAILURE_AT = None
        get_reranker.last_cache_status = (  # type: ignore[attr-defined]
            "cold" if after.misses > before.misses else "warm"
        )
        return model


def _sigmoid(value: float) -> float:
    if value >= 0:
        return 1 / (1 + math.exp(-value))
    exp_value = math.exp(value)
    return exp_value / (1 + exp_value)


def build_rerank_query(
    topic: str,
    target_skill_nodes: list[str] | None = None,
    weak_points: list[str] | None = None,
    difficulty: str | None = None,
) -> str:
    """Build one stable learning-task query for query-passage scoring."""
    parts = [f"学习主题：{topic.strip()}"]
    nodes = [item for item in (target_skill_nodes or []) if item]
    weaknesses = [item for item in (weak_points or []) if item]
    if nodes:
        parts.append(f"目标能力节点：{'、'.join(nodes)}")
    if weaknesses:
        parts.append(f"需要补齐的知识点：{'、'.join(weaknesses)}")
    if difficulty:
        parts.append(f"学习难度：{difficulty}")
    return "；".join(parts)


def mark_rerank_fallback(
    candidates: list[tuple[Document, float]],
    top_k: int,
    status: str,
) -> list[tuple[Document, float]]:
    """Return hybrid ordering with an explicit reranker fallback status."""
    results: list[tuple[Document, float]] = []
    for hybrid_rank, (source, hybrid_score) in enumerate(candidates[:top_k], start=1):
        document = Document(page_content=source.page_content, metadata=dict(source.metadata))
        document.metadata.update(
            {
                "retrieval_method": "hybrid_rrf",
                "hybrid_rank": hybrid_rank,
                "hybrid_score": float(hybrid_score),
                "rerank_status": status,
                "rerank_rank": None,
                "rerank_raw_score": None,
                "rerank_score": None,
                "final_score": float(hybrid_score),
            }
        )
        results.append((document, float(hybrid_score)))
    return results


def _select_diverse_results(
    ranked: list[tuple[Document, float]],
    top_k: int,
    max_per_document: int,
) -> list[tuple[Document, float]]:
    selected: list[tuple[Document, float]] = []
    deferred: list[tuple[Document, float]] = []
    counts: dict[str, int] = {}
    for item in ranked:
        document = item[0]
        document_id = str(
            document.metadata.get("document_id")
            or document.metadata.get("source_path")
            or document.metadata.get("chunk_id")
            or "unknown"
        )
        if counts.get(document_id, 0) >= max_per_document:
            deferred.append(item)
            continue
        selected.append(item)
        counts[document_id] = counts.get(document_id, 0) + 1
        if len(selected) >= top_k:
            return selected

    # Small or single-document corpora should still return the requested count.
    selected.extend(deferred[: max(0, top_k - len(selected))])
    return selected[:top_k]


def rerank_documents(
    query: str | Sequence[str],
    candidates: list[tuple[Document, float]],
    top_k: int,
    *,
    profile: dict[str, object] | None = None,
) -> list[tuple[Document, float]]:
    """Score query-passage pairs, then select a diverse final evidence set."""
    if top_k <= 0:
        raise ValueError("top_k 必须大于 0")
    if not candidates:
        return []

    settings = get_settings()
    if not settings.rerank_enabled:
        if profile is not None:
            profile.update(
                rerank_status="disabled",
                rerank_model_load_ms=0.0,
                rerank_inference_ms=0.0,
                rerank_candidate_count=min(len(candidates), settings.rerank_candidate_k),
                rerank_pair_count=0,
                rerank_fallback_count=1,
                fallback_reason="reranker_disabled",
            )
        return mark_rerank_fallback(candidates, top_k, "disabled")

    limited_candidates = candidates[: settings.rerank_candidate_k]
    pair_queries = [query] * len(limited_candidates) if isinstance(query, str) else list(query)
    if len(pair_queries) != len(limited_candidates):
        raise ValueError("rerank query count must match candidate count")
    pairs = [
        (pair_query, document.page_content)
        for pair_query, (document, _) in zip(pair_queries, limited_candidates)
    ]
    load_started = perf_counter()
    try:
        model = get_reranker()
    except Exception:
        if profile is not None:
            profile.update(
                rerank_model_load_ms=round((perf_counter() - load_started) * 1000, 3),
                rerank_status="model_load_failed",
            )
        raise
    model_load_ms = round((perf_counter() - load_started) * 1000, 3)
    started = perf_counter()
    raw_output = model.predict(
        pairs,
        batch_size=settings.rerank_batch_size,
        show_progress_bar=False,
        convert_to_numpy=True,
    )
    latency_ms = round((perf_counter() - started) * 1000, 3)
    if profile is not None:
        profile.update(
            rerank_status="available",
            rerank_model_load_ms=model_load_ms,
            rerank_model_cache_status=getattr(get_reranker, "last_cache_status", "unknown"),
            rerank_inference_ms=latency_ms,
            rerank_candidate_count=len(limited_candidates),
            rerank_pair_count=len(pairs),
            rerank_fallback_count=0,
        )

    if hasattr(raw_output, "reshape"):
        raw_values = [float(value) for value in raw_output.reshape(-1).tolist()]
    elif isinstance(raw_output, (list, tuple)):
        raw_values = [float(value) for value in raw_output]
    else:
        raw_values = [float(raw_output)]
    if len(raw_values) != len(limited_candidates):
        raise RuntimeError("RERANK_SCORE_COUNT_MISMATCH")

    scored: list[tuple[Document, float]] = []
    for hybrid_rank, ((source, hybrid_score), raw_score, pair_query) in enumerate(
        zip(limited_candidates, raw_values, pair_queries),
        start=1,
    ):
        document = Document(page_content=source.page_content, metadata=dict(source.metadata))
        rerank_score = _sigmoid(raw_score)
        document.metadata.update(
            {
                "retrieval_method": "hybrid_rrf_cross_encoder",
                "hybrid_rank": hybrid_rank,
                "hybrid_score": float(hybrid_score),
                "rerank_status": "available",
                "rerank_raw_score": raw_score,
                "rerank_score": rerank_score,
                "reranker_model": settings.rerank_model,
                "rerank_query_hash": hashlib.sha256(pair_query.encode("utf-8")).hexdigest()[:20],
                "rerank_latency_ms": latency_ms,
                "rerank_candidate_count": len(limited_candidates),
            }
        )
        scored.append((document, rerank_score))

    scored.sort(
        key=lambda item: (
            item[1],
            float(item[0].metadata.get("hybrid_score", 0.0)),
            str(item[0].metadata.get("chunk_id", "")),
        ),
        reverse=True,
    )
    for rerank_rank, (document, rerank_score) in enumerate(scored, start=1):
        document.metadata["rerank_rank"] = rerank_rank
        document.metadata["final_score"] = rerank_score

    return _select_diverse_results(
        scored,
        top_k=top_k,
        max_per_document=settings.rerank_max_chunks_per_document,
    )
