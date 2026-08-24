from app.core.courseware.renderer import render_courseware
from app.core.courseware.runtime import RUNTIME_VERSION, SCRIPT


def _document(block):
    return {"title": "v2 互动", "scenes": [{
        "scene_id": "scene-1", "kind": "scenario", "title": "互动",
        "source_refs": ["r1"], "component_blocks": [block],
    }]}


def _ref():
    return [{"source_resource_id": "r1", "source_block_ids": ["b1"]}]


def test_v2_interactive_components_are_rendered_with_accessible_controls_and_runtime_hooks():
    cases = {
        "branching_scenario": {"start_node_id": "n1", "nodes": [
            {"node_id": "n1", "node_type": "decision", "source_refs": _ref(), "options": [
                {"option_id": "o1", "label": "走 A", "next_node_id": "n2", "source_refs": _ref()},
                {"option_id": "o2", "label": "走 B", "next_node_id": "n2", "source_refs": _ref()},
            ]},
            {"node_id": "n2", "node_type": "terminal", "source_refs": _ref(), "options": []},
        ]},
        "categorization": {"categories": [
            {"category_id": "c1", "label": "类别 1", "source_refs": _ref()},
            {"category_id": "c2", "label": "类别 2", "source_refs": _ref()},
        ], "items": [
            {"item_id": "i1", "label": "项目 1", "correct_category_id": "c1", "source_refs": _ref()},
            {"item_id": "i2", "label": "项目 2", "correct_category_id": "c2", "source_refs": _ref()},
            {"item_id": "i3", "label": "项目 3", "correct_category_id": "c1", "source_refs": _ref()},
        ]},
        "word_bank_cloze": {"prompt_segments": ["先 ", " 再"], "blanks": [{"blank_id": "b1", "correct_token_id": "t1", "source_refs": _ref()}], "tokens": [{"token_id": "t1", "label": "检索", "source_refs": _ref()}, {"token_id": "t2", "label": "生成", "source_refs": _ref()}]},
        "timeline_explorer": {"events": [
            {"event_id": "e1", "sequence": 1, "label": "第一步", "source_refs": _ref()},
            {"event_id": "e2", "sequence": 2, "label": "第二步", "source_refs": _ref()},
        ]},
    }
    for component, payload in cases.items():
        html = render_courseware(_document({"schema_version": "2.0", "block_id": component, "component": component, "text": "来源支持内容", "source_refs": _ref(), **payload}))
        decoded = html.decode()
        assert f"data-component-id=\"{component}\"" in decoded
        assert component.replace("_", "-") in decoded
    assert RUNTIME_VERSION == "1.1"
    assert "branching_attempt" in SCRIPT
    assert "categorization_attempt" in SCRIPT
    assert "cloze_submitted" in SCRIPT
    assert "timeline_selected" in SCRIPT


def test_v2_payload_cannot_fall_back_to_v1_migration():
    from app.core.courseware.components import migrate_component_payload

    payload = {"schema_version": "2.0", "text": "来源", "source_refs": _ref(), "events": [
        {"event_id": "e1", "sequence": 1, "source_refs": _ref()},
        {"event_id": "e2", "sequence": 2, "source_refs": _ref()},
    ]}
    migrated = migrate_component_payload("timeline_explorer", payload)
    assert migrated["schema_version"] == "2.0"

