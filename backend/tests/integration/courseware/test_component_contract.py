import pytest
from pydantic import ValidationError

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSceneSpec


def _block(component):
    return {
        "block_id": "b1", "component": component, "text": "受控内容",
        "source_refs": [{"source_resource_id": "source", "source_block_ids": ["source-block"]}],
    }


def test_component_spec_uses_discriminator_and_preserves_source_mapping():
    scene = CoursewareSceneSpec.model_validate({
        "kind": "intro", "title": "开始", "blocks": [_block("key_point")],
        "feedback": "回顾来源",
        "title_source_refs": [{"source_resource_id": "source", "source_block_ids": ["source-block"]}],
    })
    assert scene.blocks[0].component == "key_point"
    source_map = scene.to_renderer_scene()["source_map"]
    assert source_map["blocks"] == [["source-block"]]
    assert source_map["title"] == [["source-block"]]
    assert source_map["feedback"] == [["source-block"]]


def test_component_spec_rejects_unknown_component_before_renderer():
    with pytest.raises(ValidationError):
        CoursewareSceneSpec.model_validate({"kind": "intro", "title": "开始", "blocks": [_block("arbitrary_html")]})
