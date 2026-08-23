from app.core.courseware.quality_summary import build_quality_summary


def test_quality_summary_separates_full_ai_from_artifact_and_is_idempotent():
    events = [
        {"event_id": "design", "stage": "design_reviewing", "status": "approved", "payload": {}},
        {"event_id": "scene", "stage": "composing", "status": "scene_approved", "scene_id": "s1", "payload": {}},
        {"event_id": "trace", "stage": "llm_observation", "scene_id": "s1", "payload": {"node_name": "courseware_scene_composer", "trace": {"model_name": "fake", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "llm_duration_ms": 20}}},
        {"event_id": "review-trace", "stage": "llm_observation", "payload": {"node_name": "courseware_quality_reviewer", "trace": {"model_name": "fake", "input_tokens": 10, "output_tokens": 5, "total_tokens": 15, "llm_duration_ms": 30}}},
        {"event_id": "review", "stage": "ai_teaching_quality", "status": "approved", "payload": {}},
    ]
    summary = build_quality_summary(events + [events[2]], status="published", artifact_success=True, spec_prompt_version="ai-v1")
    assert summary["ai_full_course_success"] is True
    assert summary["artifact_success"] is True
    assert summary["total_tokens"] == 30
    assert summary["deterministic_fallback_count"] == 0

    degraded = build_quality_summary(events, status="published_with_warnings", warnings=[{"fallback_version": "deterministic-v1"}], artifact_success=True, spec_prompt_version="ai-v1")
    assert degraded["artifact_success"] is True
    assert degraded["ai_full_course_success"] is False
    assert degraded["deterministic_fallback_count"] == 1


def test_quality_summary_requires_declared_scene_set_and_deduplicates_fallbacks():
    events = [
        {"event_id": "spec", "stage": "design_reviewing", "status": "approved", "payload": {}},
        {"event_id": "scene-1", "stage": "composing", "status": "scene_approved", "scene_id": "s1", "payload": {}},
        {"event_id": "trace-1", "stage": "llm_observation", "scene_id": "s1", "payload": {"trace": {"llm_duration_ms": 10}}},
        {"event_id": "review-trace", "stage": "llm_observation", "payload": {"node_name": "courseware_quality_reviewer", "trace": {"llm_duration_ms": 20}}},
        {"event_id": "review", "stage": "ai_teaching_quality", "status": "approved", "payload": {}},
        {"event_id": "fallback-event", "stage": "deterministic_fallback", "payload": {"occurrence_id": "fallback-1", "fallback_version": "deterministic-v1"}},
    ]
    summary = build_quality_summary(
        events,
        status="published_with_warnings",
        warnings=[{"occurrence_id": "fallback-1", "fallback_version": "deterministic-v1"}],
        artifact_success=True,
        spec_prompt_version="ai-v1",
        required_scene_ids=["s1", "s2"],
    )
    assert summary["ai_full_course_success"] is False
    assert summary["deterministic_fallback_count"] == 1
    assert summary["latency_sample_count"] == 2
    assert summary["latency_percentile_method"] == "nearest_rank"
    assert summary["latency_p95_ms"] == 20
