"""Stable, redacted AI/artifact outcome projection for courseware runs."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from math import ceil
from statistics import median
from typing import Any


def build_quality_summary(
    events: Iterable[Mapping[str, Any]], *, status: str = "not_measured", warnings: list[Mapping[str, Any]] | None = None,
    artifact_success: bool = False, spec_prompt_version: str | None = None,
    required_scene_ids: Iterable[str] | None = None,
    learning_design: Mapping[str, Any] | Any | None = None,
    scenes: Iterable[Mapping[str, Any]] | None = None,
    rubric_scores: Mapping[str, float] | None = None,
    interaction_quota: Mapping[str, Any] | None = None,
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
    scene_rows = [item for item in (scenes or ()) if isinstance(item, Mapping)]
    if not scene_rows and learning_design is not None:
        storyboard = learning_design.get("storyboard") if isinstance(learning_design, Mapping) else getattr(learning_design, "storyboard", None)
        if hasattr(storyboard, "model_dump"):
            storyboard = storyboard.model_dump(mode="json")
        scene_rows = [item for item in storyboard.get("scenes") or () if isinstance(item, Mapping)]
    usage_plan = learning_design.get("resource_usage_plan") if isinstance(learning_design, Mapping) else getattr(learning_design, "resource_usage_plan", ())
    usage_plan = [item for item in (usage_plan or ()) if isinstance(item, Mapping)]
    adopted_sources = {str(item.get("resource_id")) for item in usage_plan if item.get("adopted") and item.get("resource_id")}
    scene_sources = [set(str(value) for value in (item.get("source_refs") or item.get("source_resource_ids") or ()) if value) for item in scene_rows]
    adopted_source_count = len(adopted_sources)
    adopted_source_covered = len({value for refs in scene_sources for value in refs} & adopted_sources)
    interactive_names = {"steps", "ordered_steps", "single_choice", "multiple_choice", "flashcard", "matching", "ordering", "branching_scenario", "categorization", "word_bank_cloze", "timeline_explorer"}
    interaction_types = sorted({str(block.get("component")) for scene in scene_rows for block in (scene.get("component_blocks") or scene.get("blocks") or ()) if isinstance(block, Mapping) and block.get("component") in interactive_names})
    interactive_scene_count = sum(1 for scene in scene_rows if any(isinstance(block, Mapping) and block.get("component") in interactive_names for block in (scene.get("component_blocks") or scene.get("blocks") or ())))
    quota = interaction_quota or (learning_design.get("interaction_quota") if isinstance(learning_design, Mapping) else {}) or {}
    quota_target = quota.get("target") if isinstance(quota, Mapping) else None
    quota_actual = quota.get("actual", len(interaction_types)) if isinstance(quota, Mapping) else len(interaction_types)
    quota_status = quota.get("status", "not_measured" if not quota else "met") if isinstance(quota, Mapping) else "not_measured"
    scores = dict(rubric_scores or {})
    if not scores:
        for event in values:
            payload = event.get("payload") or {}
            candidate = payload.get("rubric_scores") or payload.get("review", {}).get("rubric_scores")
            if isinstance(candidate, Mapping):
                scores = {str(key): float(value) for key, value in candidate.items() if isinstance(value, (int, float))}
                break
    rubric_passed = bool(scores) and sum(scores.values()) / len(scores) >= 3.0 and all(value >= 2.0 for value in scores.values()) and all(scores.get(key, 0) >= 3.0 for key in ("objective_alignment", "feedback_quality", "interaction_purpose"))
    required_recovery_rate = (ai_scene_success_count / len(ai_scene_ids)) if ai_scene_ids else None
    return {
        "schema_version": "2.0", "ai_path_attempted": bool(observations or spec_success),
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
        "publication_success": status in {"published", "published_with_warnings"},
        "required_scene_recovery_rate": required_recovery_rate,
        "adopted_source_coverage": (adopted_source_covered / adopted_source_count) if adopted_source_count else None,
        "cross_source_scene_count": sum(1 for refs in scene_sources if len(refs) >= 2),
        "scene_count": len(scene_rows) if scene_rows else len(ai_scene_ids),
        "interactive_scene_count": interactive_scene_count,
        "unique_interaction_types": interaction_types,
        "interaction_quota_status": quota_status,
        "interaction_quota_target": quota_target,
        "interaction_quota_actual": quota_actual,
        "rubric_scores": scores,
        "rubric_passed": rubric_passed,
        "metric_provenance": {
            "required_scene_recovery_rate": {"numerator": ai_scene_success_count, "denominator": len(ai_scene_ids)},
            "adopted_source_coverage": {"numerator": adopted_source_covered, "denominator": adopted_source_count},
            "latency_p95": {"sample_count": len(latencies), "method": "nearest_rank"},
        },
    }


__all__ = ["build_quality_summary"]
