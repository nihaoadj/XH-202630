from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.services.courseware.composition import compose_scenes
from app.models.courseware.snapshots import LearnerContextSnapshot
from app.models.courseware.snapshots import ResourceBundleSnapshot
import pytest


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
    assert not any(item["code"] == "ASSESSMENT_SCENE_OPTIONAL" for item in design.warnings)


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


@pytest.mark.parametrize(("resource_type", "role", "primary_kind", "exercise_items"), [
    ("讲义", "lecture", "explain", []),
    ("实操指南", "practice", "practice", []),
    ("分阶测试题", "assessment", "quiz", [{"question": "选择", "options": ["A", "B"], "answer": "A"}]),
    ("复习清单", "checklist", "practice", []),
    ("案例分析", "case_study", "scenario", []),
])
def test_resource_scoped_design_selects_the_interaction_matching_its_source_type(
    resource_type, role, primary_kind, exercise_items,
):
    design = build_learning_design([{
        "resource_id": "source-1", "resource_type": resource_type, "role": role,
        "version": 1, "content_hash": "h-source", "content": "第一步理解来源。\n第二步完成验证。",
        "knowledge_points": ["关键点"], "blocks": [
            {"block_id": "b1", "text": "第一步理解来源。"}, {"block_id": "b2", "text": "第二步完成验证。"},
        ], "exercise_items": exercise_items,
    }])

    expected_kinds = ["intro", primary_kind]
    if role == "practice":
        expected_kinds = ["intro", "practice", "practice"]
    assert [scene.kind for scene in design.storyboard.scenes] == expected_kinds
    assert all(scene.source_resource_ids == ("source-1",) for scene in design.storyboard.scenes)


def test_practice_guide_creates_one_detailed_page_per_numbered_source_step():
    design = build_learning_design([{
        "resource_id": "guide-1", "resource_type": "实操指南", "role": "practice",
        "version": 1, "content_hash": "guide-hash", "knowledge_points": ["RAG"],
        "content": "步骤 1：准备环境\n安装依赖并创建虚拟环境。\n步骤 2：构建索引\n导入文档并检查索引条数。\n步骤 3：检索验证\n输入问题并核对返回的来源。",
        "blocks": [
            {"block_id": "s1", "text": "步骤 1：准备环境"},
            {"block_id": "s1-detail", "text": "安装依赖并创建虚拟环境。"},
            {"block_id": "s2", "text": "步骤 2：构建索引"},
            {"block_id": "s2-detail", "text": "导入文档并检查索引条数。"},
            {"block_id": "s3", "text": "步骤 3：检索验证"},
            {"block_id": "s3-detail", "text": "输入问题并核对返回的来源。"},
        ],
    }])

    practice_scenes = [scene for scene in design.storyboard.scenes if scene.kind == "practice"]
    assert [scene.scene_id for scene in practice_scenes] == [
        "scene:practice:guide-1:step:1", "scene:practice:guide-1:step:2", "scene:practice:guide-1:step:3",
    ]
    assert [scene.source_block_ids for scene in practice_scenes] == [
        ("s1", "s1-detail"), ("s2", "s2-detail"), ("s3", "s3-detail"),
    ]
    assert [scene.layout_recipe_id for scene in practice_scenes] == [
        "practice_workspace", "practice_workspace", "practice_workspace",
    ]
    assert [scene.practice_variant for scene in practice_scenes] == ["guided", "guided", "guided"]


def test_practice_step_page_keeps_detail_but_has_one_completion_action():
    snapshot = {
        "resource_id": "guide-1", "resource_type": "实操指南", "role": "practice", "version": 1,
        "content_hash": "guide-hash", "topic": "RAG 实操", "knowledge_points": [],
        "content": "步骤 1：准备环境\n创建虚拟环境。\n安装项目所需依赖。\n确认命令可运行。\n步骤 2：构建索引\n导入文档。",
        "blocks": [
            {"block_id": "s1", "text": "步骤 1：准备环境"}, {"block_id": "s1a", "text": "创建虚拟环境。"},
            {"block_id": "s1b", "text": "安装项目所需依赖。"}, {"block_id": "s1c", "text": "确认命令可运行。"},
            {"block_id": "s2", "text": "步骤 2：构建索引"}, {"block_id": "s2a", "text": "导入文档。"},
        ],
    }
    design = build_learning_design([snapshot])
    scenes, warnings = compose_scenes([snapshot], learning_design=design)

    assert warnings == []
    first_step = next(scene for scene in scenes if scene["scene_id"] == "scene:practice:guide-1:step:1")
    assert first_step["title"].startswith("步骤 1｜准备环境")
    assert first_step["steps"] == ["我已完成本步骤并核对预期结果"]
    assert "创建虚拟环境。" in first_step["blocks"][1]
    assert "安装项目所需依赖。" in first_step["blocks"][1]
    assert "确认命令可运行。" in first_step["blocks"][1]
    assert first_step["source_block_ids"] == ["s1", "s1a", "s1b", "s1c"]


def test_practice_cover_uses_resource_topic_and_has_no_generic_question_or_final_summary():
    snapshot = {
        "resource_id": "guide-cover", "resource_type": "实操指南", "role": "practice", "version": 1,
        "content_hash": "guide-cover-hash", "topic": "RAG 工程链路实操指南｜复习清单",
        "knowledge_points": ["chunking"], "content": "步骤 1：准备环境\n安装依赖。",
        "blocks": [
            {"block_id": "prepare", "text": "步骤 1：准备环境"},
            {"block_id": "detail", "text": "安装依赖。"},
        ],
    }
    design = build_learning_design([snapshot])
    scenes, warnings = compose_scenes([snapshot], learning_design=design)

    assert warnings == []
    assert not any(scene.get("page_role") == "summary_action" for scene in scenes)
    cover = scenes[0]
    assert cover["title"] == "RAG 工程链路实操指南"
    assert "这门课程能帮助我解决什么问题" not in render_courseware({"title": "x", "scenes": [cover]}).decode()
    assert "学习目标：" in "\n".join(cover["blocks"])


def test_llm_validated_practice_structure_controls_step_grouping():
    snapshot = {
        "resource_id": "guide-1", "resource_type": "实操指南", "role": "practice", "version": 1,
        "content_hash": "guide-hash", "content": "准备\n安装\n索引\n验证", "knowledge_points": [],
        "blocks": [
            {"block_id": "b1", "text": "准备项目目录"}, {"block_id": "b2", "text": "安装所需依赖"},
            {"block_id": "b3", "text": "构建向量索引"}, {"block_id": "b4", "text": "执行检索验证"},
        ],
    }
    design = build_learning_design([snapshot], practice_step_structures={
        "guide-1": [
            {"title": "准备运行环境", "source_block_ids": ["b1", "b2"]},
            {"title": "构建并验证索引", "source_block_ids": ["b3", "b4"]},
        ],
    })
    pages = [scene for scene in design.storyboard.scenes if scene.kind == "practice"]
    assert [scene.key_question for scene in pages] == [
        "步骤 1：准备运行环境 应如何完成并验收？", "步骤 2：构建并验证索引 应如何完成并验收？",
    ]
    assert [scene.source_block_ids for scene in pages] == [("b1", "b2"), ("b3", "b4")]


def test_dense_real_step_can_use_two_detail_pages_without_becoming_two_steps():
    snapshot = {
        "resource_id": "guide-1", "resource_type": "实操指南", "role": "practice", "version": 1,
        "content_hash": "guide-hash", "content": "步骤 1：建立索引", "knowledge_points": [],
        "blocks": [
            {"block_id": "h1", "kind": "heading", "text": "### 步骤 1：建立索引"},
            {"block_id": "p1", "kind": "paragraph", "text": "准备材料。" * 220},
            {"block_id": "code", "kind": "code", "text": "```python\nbuild_index()\n```"},
            {"block_id": "p2", "kind": "paragraph", "text": "执行后核对索引条数。" * 120},
        ],
    }
    design = build_learning_design([snapshot])
    pages = [scene for scene in design.storyboard.scenes if scene.kind == "practice"]

    assert [scene.scene_id for scene in pages] == [
        "scene:practice:guide-1:step:1:part:1", "scene:practice:guide-1:step:1:part:2",
    ]
    assert all("apply-step-1" in scene.interaction_purpose for scene in pages)
    assert [scene.source_block_ids for scene in pages] == [("h1", "p1", "code"), ("p2",)]


def test_fallback_only_uses_explicit_step_headings_not_preamble_or_checklist_lines():
    blocks = [{"block_id": "intro", "kind": "paragraph", "text": "准备说明"}]
    for number in range(1, 10):
        blocks.extend([
            {"block_id": f"h{number}", "kind": "heading", "text": f"### 步骤 {number}：操作 {number}"},
            {"block_id": f"d{number}", "kind": "paragraph", "text": f"执行操作 {number} 并核对结果。"},
        ])
    blocks.append({"block_id": "appendix", "kind": "heading", "text": "## 检查清单"})
    snapshot = {
        "resource_id": "guide-1", "resource_type": "实操指南", "role": "practice", "version": 1,
        "content_hash": "guide-hash", "content": "示例", "knowledge_points": [], "blocks": blocks,
    }
    design = build_learning_design([snapshot])
    pages = [scene for scene in design.storyboard.scenes if scene.kind == "practice"]

    assert len(pages) == 9
    assert [scene.scene_id for scene in pages] == [f"scene:practice:guide-1:step:{number}" for number in range(1, 10)]
