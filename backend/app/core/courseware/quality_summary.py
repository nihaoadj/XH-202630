"""Stable, redacted AI/artifact outcome projection for courseware runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import ceil
from statistics import median
from typing import Any


def build_quality_summary(
    events: Iterable[Mapping[str, Any]], *, status: str, warnings: list[Mapping[str, Any]] | None = None,
    artifact_success: bool = False, spec_prompt_version: str | None = None,
    required_scene_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Aggregate persisted facts once per event ID without exposing prompts."""
    unique = {str(event.get("event_id")): event for event in events if event.get("event_id")}
    values = list(unique.values())
    observations = [event for event in values if event.get("stage") == "llm_observation"]
    traces = [(event.get("payload") or {}).get("trace") or {} for event in observations]
    scene_observations = {event.get("scene_id") for event in observations if event.get("scene_id")}
    approved_scenes = {event.get("scene_id") for event in values if event.get("stage") == "composing" and event.get("status") == "scene_approved"}
    spec_success = spec_prompt_version == "ai-v1" and any(event.get("stage") == "design_reviewing" and event.get("status") in {"approved", "reused"} for event in values)
    review_success = any((event.get("payload") or {}).get("node_name") == "courseware_quality_reviewer" for event in observations) and any(event.get("stage") == "ai_teaching_quality" and event.get("status") == "approved" for event in values)
    revision_attempted = sum(event.get("stage") == "auto_revising" and event.get("status") == "started" for event in values)
    revision_success = sum(event.get("stage") == "auto_revising" and event.get("status") == "approved" for event in values)
    fallback_keys: set[tuple[str, ...]] = set()
    for event in values:
        if event.get("stage") != "deterministic_fallback":
            continue
        payload = event.get("payload") or {}
        fallback_keys.add((
            str(payload.get("occurrence_id") or event.get("occurrence_id") or ""),
            str(payload.get("candidate_id") or event.get("candidate_id") or ""),
            str(event.get("stage") or ""), str(event.get("scene_id") or ""),
            str(payload.get("fallback_version") or ""),
        ))
    for item in warnings or []:
        if not isinstance(item, Mapping) or not item.get("fallback_version"):
            continue
        fallback_keys.add((
            str(item.get("occurrence_id") or ""), str(item.get("candidate_id") or ""),
            str(item.get("stage") or "deterministic_fallback"), str(item.get("scene_id") or ""),
            str(item.get("fallback_version") or ""),
        ))
    fallback_count = len(fallback_keys)
    latencies = [int(trace.get("llm_duration_ms")) for trace in traces if isinstance(trace.get("llm_duration_ms"), (int, float))]
    input_tokens = sum(int(trace.get("input_tokens") or 0) for trace in traces)
    output_tokens = sum(int(trace.get("output_tokens") or 0) for trace in traces)
    total_tokens = sum(int(trace.get("total_tokens") or (int(trace.get("input_tokens") or 0) + int(trace.get("output_tokens") or 0))) for trace in traces)
    routes = [str(trace.get("model_name")) for trace in traces if trace.get("model_name")]
    declared_scene_ids = {str(item) for item in (required_scene_ids or ()) if str(item)}
    # A deterministic recap can be part of the released artifact even when it
    # has no model observation. Callers may therefore declare the frozen AI
    # scene set; the legacy fallback remains observation-based for old reports.
    ai_scene_ids = declared_scene_ids or scene_observations
    ai_scene_success_count = len(approved_scenes & ai_scene_ids)
    full_ai = bool(spec_success and ai_scene_ids and ai_scene_ids.issubset(approved_scenes)
                   and review_success and revision_success >= revision_attempted and fallback_count == 0)
    p95 = None
    if latencies:
        ordered = sorted(latencies)
        p95 = ordered[max(0, ceil(0.95 * len(ordered)) - 1)]
    return {
        "schema_version": "1.0", "ai_path_attempted": bool(observations or spec_success),
        "ai_spec_success": spec_success, "ai_scene_success_count": ai_scene_success_count, "ai_scene_total": len(ai_scene_ids),
        "ai_review_success": review_success, "ai_revision_attempted": revision_attempted, "ai_revision_success": revision_success,
        "schema_repair_count": sum(int(trace.get("schema_repair_count") or 0) for trace in traces), "schema_repair_success": sum(int(trace.get("schema_repair_success") or 0) for trace in traces),
        "primary_route": routes[0] if routes else None, "secondary_routes": sorted(set(routes[1:])), "ai_full_course_success": full_ai,
        "deterministic_fallback_count": fallback_count, "artifact_success": bool(artifact_success), "status": status,
        "input_tokens": input_tokens, "output_tokens": output_tokens, "total_tokens": total_tokens,
        "retry_count": sum(int(trace.get("retry_count") or 0) for trace in traces),
        "latency_sample_count": len(latencies), "latency_percentile_method": "nearest_rank",
        "latency_p50_ms": int(median(latencies)) if latencies else None, "latency_p95_ms": p95,
        "estimated_cost": round(sum(float(trace.get("estimated_cost_usd") or 0) for trace in traces), 8),
    }


__all__ = ["build_quality_summary"]
