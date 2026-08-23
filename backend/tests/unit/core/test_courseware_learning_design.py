from app.core.courseware.learning_design import build_learning_design
from app.models.courseware.snapshots import LearnerContextSnapshot
from app.models.courseware.snapshots import ResourceBundleSnapshot


def _snapshots(include_assessment=True, practice_content="第一步：配置环境"):
    rows = [
        {
            "resource_id": "lecture-1", "resource_type": "讲义", "role": "lecture", "version": 1,
            "content_hash": "h-lecture", "content": "核心概念", "knowledge_points": ["概念 A"],
            "blocks": [{"block_id": "b1", "text": "核心概念"}],
        },
        {
            "resource_id": "practice-1", "resource_type": "实操指南", "role": "practice", "version": 1,
            "content_hash": "h-practice", "content": practice_content, "knowledge_points": [],
            "blocks": [{"block_id": "p1", "text": practice_content}],
        },
    ]
    if include_assessment:
        rows.append({
            "resource_id": "assessment-1", "resource_type": "分阶测试题", "role": "assessment", "version": 1,
            "content_hash": "h-assessment", "content": "题目", "knowledge_points": [],
            "blocks": [{"block_id": "q1", "text": "题目"}],
            "exercise_items": [{"question": "选择", "options": ["A", "B"], "answer": "A"}],
        })
    return rows


def test_design_is_stable_and_binds_interactions_to_source_and_objective():
    first = build_learning_design(_snapshots())
    second = build_learning_design(_snapshots())
    assert first.resource_bundle_hash == second.resource_bundle_hash
    assert first.objectives.stable_hash() == second.objectives.stable_hash()
    practice = next(item for item in first.storyboard.scenes if item.kind == "practice")
    quiz = next(item for item in first.storyboard.scenes if item.kind == "quiz")
    assert practice.source_resource_ids == ("practice-1",)
    assert practice.objective_ids == ("objective:practice-1",)
    assert quiz.source_resource_ids == ("assessment-1",)
    assert quiz.objective_ids == ("objective:assessment-1",)


def test_missing_assessment_is_optional_and_never_fabricates_quiz():
    design = build_learning_design(_snapshots(include_assessment=False))
    assert not any(scene.kind == "quiz" for scene in design.storyboard.scenes)
    assert any(item["code"] == "ASSESSMENT_SCENE_OPTIONAL" for item in design.warnings)


def test_empty_practice_has_no_steps_scene_and_context_only_changes_design_tuning():
    base = build_learning_design(_snapshots(practice_content=""), LearnerContextSnapshot(pace="slow"))
    fast = build_learning_design(_snapshots(practice_content=""), LearnerContextSnapshot(pace="fast"))
    assert not any(scene.kind == "practice" for scene in base.storyboard.scenes)
    assert base.resource_bundle_hash == fast.resource_bundle_hash
    assert base.objectives.stable_hash() == fast.objectives.stable_hash()
    assert base.learner_context_hash != fast.learner_context_hash


def test_frozen_resource_bundle_keeps_cross_batch_fusion_metadata():
    bundle = ResourceBundleSnapshot.from_snapshot({
        "resource_id": "lecture-cross-batch", "resource_type": "讲义", "role": "lecture",
        "version": 2, "content_hash": "hash", "batch_id": "batch-older", "topic": "RAG 基础",
        "knowledge_points": ["检索", "生成"], "exercise_items": [{"question": "选择", "answer": "检索"}],
        "blocks": [{"block_id": "b1", "text": "先检索"}],
    })

    assert bundle.batch_id == "batch-older"
    assert bundle.topic == "RAG 基础"
    assert bundle.knowledge_points == ("检索", "生成")
    assert bundle.has_verifiable_exercises is True
