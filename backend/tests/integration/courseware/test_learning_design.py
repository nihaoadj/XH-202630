from app.core.courseware.learning_design import build_learning_design


def test_learning_design_persists_stable_bundle_and_optional_quiz_warning():
    snapshots = [{
        "resource_id": "lecture-1", "resource_type": "讲义", "role": "lecture", "version": 2,
        "content_hash": "lecture-hash", "content": "核心概念", "knowledge_points": ["概念 A"],
        "blocks": [{"block_id": "b1", "text": "核心概念"}],
    }]
    first = build_learning_design(snapshots)
    second = build_learning_design(snapshots)
    assert first.resource_bundle_hash == second.resource_bundle_hash
    assert not any(scene.kind == "quiz" for scene in first.storyboard.scenes)
    assert any(warning["code"] == "ASSESSMENT_SCENE_OPTIONAL" for warning in first.warnings)


def test_practice_and_quiz_slots_are_source_and_objective_bound():
    snapshots = [
        {
            "resource_id": "practice-1", "resource_type": "实操指南", "role": "practice", "version": 1,
            "content_hash": "practice-hash", "content": "第一步：配置", "knowledge_points": [],
            "blocks": [{"block_id": "p1", "text": "第一步：配置"}],
        },
        {
            "resource_id": "assessment-1", "resource_type": "分阶测试题", "role": "assessment", "version": 1,
            "content_hash": "assessment-hash", "content": "题目", "knowledge_points": [],
            "blocks": [{"block_id": "q1", "text": "题目"}],
            "exercise_items": [{"question": "选择", "options": ["A", "B"], "answer": "A"}],
        },
    ]
    design = build_learning_design(snapshots)
    assert [(scene.kind, scene.source_resource_ids, scene.objective_ids) for scene in design.storyboard.scenes if scene.kind in {"practice", "quiz"}] == [
        ("practice", ("practice-1",), ("objective:practice-1",)),
        ("quiz", ("assessment-1",), ("objective:assessment-1",)),
    ]


def test_resource_usage_plan_explains_adoption_and_duplicate_sources():
    snapshots = [
        {
            "resource_id": "lecture-a", "resource_type": "讲义", "role": "lecture", "version": 1,
            "content_hash": "same-content", "content": "核心概念", "knowledge_points": ["概念 A"],
            "resource_family_id": "family-a", "blocks": [{"block_id": "a1", "text": "核心概念"}],
        },
        {
            "resource_id": "lecture-b", "resource_type": "讲义", "role": "lecture", "version": 1,
            "content_hash": "same-content", "content": "核心概念", "knowledge_points": ["概念 A"],
            "resource_family_id": "family-a", "blocks": [{"block_id": "b1", "text": "核心概念"}],
        },
    ]
    design = build_learning_design(snapshots)
    usage = {item["resource_id"]: item for item in design.resource_usage_plan}
    assert usage["lecture-a"]["adopted"] is True
    assert usage["lecture-a"]["scene_ids"]
    assert usage["lecture-b"]["adopted"] is False
    assert usage["lecture-b"]["unused_reason"] == "duplicate_source"
