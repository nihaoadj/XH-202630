from app.core.courseware.evaluation import quality_gate_report


def test_quality_gate_fails_missing_objective_binding_and_marks_visual_external():
    report = quality_gate_report({"title": "x", "scenes": [{"scene_id": "s", "kind": "intro", "blocks": ["x"], "source_refs": ["r"], "source_block_ids": ["b"]}]}, snapshots=[])
    assert "interaction.interaction_bound_to_objective" in report["failed_dimensions"]
    assert report["dimensions"]["visual"]["contrast"] == "not_measured"
