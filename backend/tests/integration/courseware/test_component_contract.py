import pytest
from pydantic import ValidationError
import json
from pathlib import Path

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


@pytest.mark.parametrize(
    ("component", "extra"),
    [
        ("flashcard", {"front": "问题"}),
        ("matching", {"pairs": [{"left": "A"}]}),
        ("ordering", {"ordering_items": ["A", "B"], "correct_order": ["A"]}),
    ],
)
def test_interactive_components_require_complete_versioned_payloads(component, extra):
    with pytest.raises(ValidationError):
        CoursewareSceneSpec.model_validate({
            "kind": "intro", "title": "互动", "blocks": [{**_block(component), **extra}],
        })


def test_component_fixture_matches_platform_catalog():
    from app.core.courseware.components.catalog import CATALOG_V1

    fixture = json.loads(Path("backend/tests/fixtures/courseware/components/catalog_v1.json").read_text(encoding="utf-8"))
    assert fixture["components"] == sorted(CATALOG_V1)
