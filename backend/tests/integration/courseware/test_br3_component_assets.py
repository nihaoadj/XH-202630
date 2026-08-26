import pytest

from app.core.courseware.components import component_definition, migrate_component_payload, validate_component_payload
from app.core.courseware.renderer import render_courseware


def test_each_component_has_payload_validation_and_unknown_version_rejection():
    for name in ("callout", "key_point", "compare", "steps", "ordered_steps", "single_choice", "multiple_choice", "recap"):
        assert component_definition(name, "1.0") is not None
        assert validate_component_payload(name, {"schema_version": "1.0", "text": "脱敏", "source_refs": [{"source_resource_id": "r", "source_block_ids": ["b"]}]})
    with pytest.raises(ValueError):
        migrate_component_payload("callout", {"schema_version": "9.0", "text": "x"})


def test_choice_components_have_distinct_form_semantics():
    base = {"title": "x", "scenes": [{"scene_id": "s", "kind": "intro", "title": "x", "blocks": ["x"], "source_refs": ["r"], "source_block_ids": ["b"], "component_blocks": []}]}
    for component in ("single_choice", "multiple_choice"):
        doc = {**base, "scenes": [{**base["scenes"][0], "component_blocks": [{"block_id": "b", "component": component, "text": "选择", "options": ["a", "b"], "source_refs": [{"source_resource_id": "r", "source_block_ids": ["b"]}]}]}]}
        html = render_courseware(doc).decode()
        assert ('type="radio"' in html) == (component == "single_choice")
