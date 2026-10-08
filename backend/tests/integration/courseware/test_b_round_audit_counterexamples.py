"""Counterexamples from the B-round audit; these must fail before each repair."""

from app.core.courseware.evaluation import quality_gate_report
from app.core.courseware.renderer import render_courseware
from app.models.courseware.snapshots import ResourceBundleSnapshot

from backend.tests.integration.courseware.test_api import _client, _run_worker


def test_public_workflow_freezes_distinct_learner_contexts_and_source_graph(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, with_quiz=False)
    service = client.app.container.courseware_service()
    service.workflow.learner_context_provider = lambda learner_id: {
        "level": "beginner" if learner_id == "courseware-learner" else "advanced",
        "pace": "slow", "accessibility_preferences": (),
    }
    created = service.create_job(__import__("app.models.courseware", fromlist=["CoursewareJobCreateRequest"]).CoursewareJobCreateRequest(
        learner_id="courseware-learner", source_resource_ids=["guide"],
    ))
    _run_worker(client)
    spec = service.repo.get_spec_by_run(created.run_id)
    design = (spec.get("spec_json") or {}).get("learning_design") or {}
    assert (spec.get("spec_json") or {}).get("learner_context_snapshot", {}).get("level") == "beginner"
    assert all((item.get("source_graph") or {}).get("nodes") for item in (spec.get("spec_json") or {}).get("resource_bundle_snapshot", []))
    assert all(scene.get("objective_ids") and scene.get("allowed_component_ids") for scene in (spec.get("spec_json") or {}).get("storyboard", {}).get("scenes", []))
    assert design.get("storyboard")


def test_layout_and_motion_have_observable_semantics_not_only_ids():
    document = {"title": "布局", "scenes": [{
        "scene_id": "s1", "kind": "intro", "title": "开始", "blocks": ["内容"],
        "source_refs": ["r1"], "source_block_ids": ["b1"],
    }]}
    outputs = [render_courseware(document, {"layout_id": layout, "motion_id": motion})
               for layout in ("cover", "chapter", "focus", "compare", "steps", "practice", "recap", "progress")
               for motion in ("subtle", "reduced")]
    assert len({output for output in outputs}) == 16
    html = outputs[0].decode("utf-8")
    assert "@keyframes" in html and ".layout-cover" in html


def test_every_component_has_real_semantics_and_single_choice_is_radio():
    components = ("callout", "key_point", "compare", "steps", "ordered_steps", "single_choice", "multiple_choice", "recap")
    rendered = []
    for component in components:
        document = {"title": component, "scenes": [{
            "scene_id": component, "kind": "intro", "title": component, "blocks": ["内容"],
            "source_refs": ["r1"], "source_block_ids": ["b1"],
            "component_blocks": [{"block_id": "b1", "component": component, "text": "内容",
                                  "source_refs": [{"source_resource_id": "r1", "source_block_ids": ["b1"]}]}],
        }]}
        rendered.append(render_courseware(document).decode("utf-8"))
    assert any('type="radio"' in html for html in rendered)
    assert any("component-steps" in html for html in rendered)
    assert all("aria-label" in html for html in rendered)


def test_quality_report_marks_unmeasured_visual_dimensions_instead_of_constant_pass():
    report = quality_gate_report({"title": "质量", "scenes": []}, snapshots=[])
    visual = report["dimensions"]["visual"]
    assert visual["contrast"] == "not_measured"
    assert visual["touch_target"] == "not_measured"
    assert "visual.contrast" in report["failed_dimensions"]
