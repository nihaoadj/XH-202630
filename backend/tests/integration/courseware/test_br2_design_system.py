import pytest

from app.core.courseware.renderer import render_courseware


def test_unknown_design_ids_are_hard_gate_failures():
    document = {"title": "x", "scenes": [{"scene_id": "s", "kind": "intro", "title": "x", "blocks": ["x"], "source_refs": ["r"], "source_block_ids": ["b"]}]}
    with pytest.raises(ValueError, match="未注册设计系统"):
        render_courseware(document, {"theme_id": "model_css", "layout_id": "cover", "motion_id": "subtle"})


def test_layout_styles_are_real_rules_and_reduced_motion_disables_animation():
    document = {"title": "x", "scenes": [{"scene_id": "s", "kind": "intro", "title": "x", "blocks": ["x"], "source_refs": ["r"], "source_block_ids": ["b"]}]}
    cover = render_courseware(document, {"layout_id": "cover", "motion_id": "subtle"}).decode()
    reduced = render_courseware(document, {"layout_id": "steps", "motion_id": "reduced"}).decode()
    assert ".layout-cover .course-header" in cover and "@keyframes courseware-enter" in cover
    assert ".layout-steps .scene" in reduced and '[data-motion="reduced"]' in reduced
