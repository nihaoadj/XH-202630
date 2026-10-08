import pytest

from app.core.courseware.components import component_asset_matrix, component_definition, is_registered_component
from app.core.courseware.renderer import render_courseware


def test_component_catalog_v1_has_complete_interaction_asset_matrix():
    matrix = component_asset_matrix()
    assert set(matrix) == {
        "callout", "code_block", "key_point", "compare", "steps", "ordered_steps", "single_choice", "multiple_choice", "recap",
        "flashcard", "matching", "ordering",
    }
    assert all(item["schema_version"] == "1.0" for item in matrix.values())
    assert all(item["renderer"] and item["runtime"] and item["keyboard_support"] for item in matrix.values())
    assert all(item["touch_target"] for name, item in matrix.items() if name in {"steps", "ordered_steps", "single_choice", "multiple_choice", "flashcard", "matching", "ordering"})


def test_unknown_component_version_is_rejected_before_rendering():
    assert component_definition("callout", "9.9") is None
    assert not is_registered_component("callout", "9.9")
    document = {
        "title": "版本拒绝", "scenes": [{
            "kind": "intro", "title": "开始", "blocks": ["内容"], "source_refs": ["r1"],
            "source_block_ids": ["b1"], "component_blocks": [{
                "schema_version": "9.9", "component": "callout", "text": "内容",
                "source_refs": [{"source_resource_id": "r1", "source_block_ids": ["b1"]}],
            }],
        }],
    }
    with pytest.raises(ValueError, match="未注册互动组件"):
        render_courseware(document)
