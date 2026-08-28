from app.core.courseware.learning_design import build_learning_design


def _source(resource_id, role="lecture", *, knowledge=None, exercise_items=None, relation=None):
    row = {
        "resource_id": resource_id, "resource_type": "讲义", "role": role, "version": 1,
        "content_hash": f"hash-{resource_id}", "content": f"内容-{resource_id}",
        "knowledge_points": knowledge or [f"概念-{resource_id}"],
        "blocks": [{"block_id": f"{resource_id}-b1", "text": "冻结来源"}],
    }
    if exercise_items is not None:
        row["exercise_items"] = exercise_items
    if relation:
        row["source_relation"] = relation
    return row


def test_duration_and_intensity_create_auditable_scene_and_interaction_quotas():
    design = build_learning_design(
        [_source("r1"), _source("r2", role="practice", exercise_items=[{"question": "q", "answer": "a"}])],
        request_options={"expected_duration_minutes": 30, "interaction_intensity": "medium"},
    )
    assert design.interaction_quota["target_scene_count"] == 11
    assert design.interaction_quota["status"] == "met"
    assert len(design.storyboard.scenes) < 9
    assert {scene.page_role for scene in design.storyboard.scenes} >= {
        "cover", "learning_map", "concept_explanation", "comparison_analysis",
    }
    assert not any(scene.page_role == "summary_action" for scene in design.storyboard.scenes)
    assert not any(scene.kind == "example" for scene in design.storyboard.scenes)
    assert any(item["code"] == "SOURCE_DENSITY_REDUCED_PAGE_COUNT" for item in design.warnings)


def test_conflict_is_explicitly_parallel_and_source_concepts_are_traceable():
    design = build_learning_design([_source("r1", relation="conflict"), _source("r2")])
    index = design.source_concept_index
    assert index is not None and index.schema_version == "2.0"
    assert {item.relation_type for item in index.relations} <= {"prerequisite", "complementary", "duplicate", "conflict"}
    assert any(item.relation_type == "conflict" for item in index.relations)
    assert all(item.source_refs or item.adopted_source_ids for item in index.concepts)
    compare = next(item for item in design.storyboard.scenes if item.kind == "compare")
    assert set(compare.source_resource_ids) == {"r1", "r2"}
    assert set(design.storyboard.scenes[-1].source_resource_ids) == {"r1", "r2"}


def test_high_quota_is_constrained_without_verifiable_evidence_and_does_not_invent_answers():
    design = build_learning_design(
        [_source("r1"), _source("r2")],
        request_options={"expected_duration_minutes": 60, "interaction_intensity": "high"},
    )
    assert design.interaction_quota["status"] == "constrained"
    assert design.interaction_quota["reason"] == "INSUFFICIENT_SCORED_EVIDENCE"
    assert not any(scene.kind == "quiz" for scene in design.storyboard.scenes)
    assert any(item["code"] == "INSUFFICIENT_SCORED_EVIDENCE" for item in design.warnings)
