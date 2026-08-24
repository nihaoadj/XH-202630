from pathlib import Path

from app.core.courseware.quality_summary import build_quality_summary
from app.core.courseware.learning_design import build_learning_design


def test_quality_summary_v2_separates_quality_dimensions_and_preserves_provenance():
    design = build_learning_design([{
        "resource_id": "r1", "resource_type": "讲义", "role": "lecture", "version": 1,
        "content_hash": "h1", "content": "内容", "knowledge_points": ["概念"],
        "blocks": [{"block_id": "b1", "text": "来源"}],
    }])
    summary = build_quality_summary([], status="published", learning_design=design, scenes=[{
        "scene_id": "scene-1", "source_refs": ["r1"],
        "component_blocks": [{"component": "branching_scenario"}],
    }])
    assert summary["schema_version"] == "2.0"
    assert summary["publication_success"] is True
    assert summary["unique_interaction_types"] == ["branching_scenario"]
    assert summary["adopted_source_coverage"] == 1.0
    assert "metric_provenance" in summary


def test_frontend_exposes_quality_summary_without_internal_prompt_or_error_payload():
    source = Path(__file__).resolve().parents[4] / "frontend/src/features/learning-documents/ResourcesView.vue"
    text = source.read_text(encoding="utf-8")
    assert "quality_summary" in text
    assert "interaction_quota_status" in text
    assert "rubric_passed" in text
    assert "prompt" not in text.lower().split("quality_summary", 1)[-1][:800]

