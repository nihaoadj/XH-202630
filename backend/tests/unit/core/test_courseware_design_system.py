from app.core.courseware.renderer import render_courseware
from app.core.courseware.design_system import THEMES, resolve_motion, resolve_theme
import pytest


def _document():
    return {
        "title": "主题测试",
        "scenes": [{
            "kind": "intro", "title": "开始", "blocks": ["内容"],
            "source_refs": ["lecture-1"], "source_block_ids": ["b1"],
        }],
    }


def test_design_system_has_versioned_themes_and_reduced_motion():
    assert set(THEMES) == {"editorial", "midnight", "paper"}
    assert resolve_theme("unknown").theme_id == "editorial"
    assert resolve_motion("subtle", prefers_reduced_motion=True).reduced_motion is True


def test_theme_switch_changes_tokens_only_not_content_or_provenance():
    editorial = render_courseware(_document(), {"theme_id": "editorial", "layout_id": "cover"})
    midnight = render_courseware(_document(), {"theme_id": "midnight", "layout_id": "cover"})
    for output in (editorial, midnight):
        assert b"source_refs" not in output
        assert "内容" in output.decode("utf-8")
        assert "lecture-1" not in output.decode("utf-8")
    assert editorial != midnight


def test_unknown_design_ids_are_rejected_and_reduced_motion_css_exists():
    with pytest.raises(ValueError):
        render_courseware(_document(), {"theme_id": "not-a-theme", "layout_id": "not-a-layout", "motion_id": "reduced"})
    html = render_courseware(_document(), {"motion_id": "reduced"}).decode("utf-8")
    assert 'data-motion="reduced"' in html
    assert "prefers-reduced-motion" in html
