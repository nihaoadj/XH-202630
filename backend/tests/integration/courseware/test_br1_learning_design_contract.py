from app.agents.resource_workflows.interactive_courseware.validators import validate_storyboard_bindings


def test_storyboard_slot_rejects_unknown_objective_source_and_component():
    design = {
        "storyboard": {"scenes": [{
            "scene_id": "scene:practice:x", "kind": "practice",
            "objective_ids": ["objective:x"], "source_resource_ids": ["x"],
            "source_block_ids": ["b1"], "allowed_component_ids": ["steps"],
        }]}
    }
    scene = {"scene_id": "scene:practice:x", "kind": "practice", "objective_ids": ["objective:bad"],
             "source_refs": ["x"], "source_block_ids": ["missing"], "component_blocks": [{"component": "quiz"}]}
    errors = validate_storyboard_bindings(scene, design)
    assert {"objective_ids", "source_block_ids", "component_ids"}.issubset(set(errors))


def test_storyboard_slot_accepts_only_bound_payload():
    design = {"storyboard": {"scenes": [{
        "scene_id": "scene:intro", "kind": "intro", "objective_ids": ["objective:x"],
        "source_resource_ids": ["x"], "source_block_ids": ["b1"], "allowed_component_ids": ["callout"],
    }]}}
    scene = {"scene_id": "scene:intro", "kind": "intro", "objective_ids": ["objective:x"],
             "source_refs": ["x"], "source_block_ids": ["b1"], "component_blocks": [{"component": "callout"}]}
    assert validate_storyboard_bindings(scene, design) == []
