import hashlib
import json
from types import SimpleNamespace

import pytest

from app.core.courseware.learning_design import build_learning_design
from app.core.courseware.renderer import render_courseware
from app.agents.resource_workflows.interactive_courseware.validators import validate_scene_shape
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.agent_contracts import PracticeGuidePackageV3
from app.services.courseware.composition import compose_scenes
from app.services.courseware.source import (
    CoursewareAdmissionError,
    ROLE_BY_TYPE,
    _snapshot,
    admit_and_snapshot,
)


def _payload_hash(payload):
    canonical = PracticeGuidePackageV3.model_validate(payload).model_dump(mode="json")
    return hashlib.sha256(
        json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_structured_practice_payload_directly_drives_courseware_step_pages():
    payload = {
        "schema_version": "3.0",
        "title": "结构化实操指南",
        "preparation": {"phase_id": "prepare", "goal": "准备环境", "items": ["创建环境"], "evidence_ids": ["ev-1"]},
        "practice": {"phase_id": "practice", "goal": "执行并验证", "steps": [
            {"step_id": "step-1", "title": "准备环境", "instruction_text": "创建可用环境。", "code_blocks": [{"language": "bash", "code": "tool init", "purpose": "初始化环境", "evidence_ids": ["ev-1"]}], "verification": "环境可用", "evidence_ids": ["ev-1"]},
            {"step_id": "step-2", "title": "执行验证", "instruction_text": "运行检查确认结果。", "code_blocks": [], "verification": "结果正确", "evidence_ids": ["ev-1"]},
        ]},
        "verification": {"phase_id": "verify", "goal": "确认完成", "checklist": ["完成验证"], "evidence_ids": ["ev-1"]},
        "reflection": {"phase_id": "reflect", "goal": "完成复盘", "summary": "根据验证结果完成复盘。", "evidence_ids": ["ev-1"]},
    }
    payload["payload_hash"] = _payload_hash(payload)
    source = LearningResource(resource_id="guide-json", resource_type="实操指南", difficulty="初级", content_text="# 旧 Markdown", knowledge_points=["node"], source_refs=[], practice_guide_payload=payload, practice_guide_payload_hash=payload["payload_hash"])

    snapshot = _snapshot(source)
    design = build_learning_design([snapshot])
    scenes, warnings = compose_scenes([snapshot], learning_design=design)

    assert [block["practice_step_id"] for block in snapshot["blocks"] if block.get("practice_step_id")] == ["step-1", "step-2"]
    practice_scenes = [scene for scene in design.storyboard.scenes if scene.kind == "practice"]
    assert [scene.practice_variant for scene in practice_scenes] == ["prepare", "code", "guided", "verify", "reflect"]
    assert warnings == []
    composed_practice_scenes = [scene for scene in scenes if scene["kind"] == "practice"]
    assert all(scene["practice_json_schema_version"] == "3.0" for scene in composed_practice_scenes)
    assert all(
        block["source_json_path"] and block["evidence_json_path"]
        for scene in composed_practice_scenes
        for block in scene["component_blocks"]
    )
    assert all(validate_scene_shape(scene) == [] for scene in composed_practice_scenes)
    reflection_scene = next(scene for scene in composed_practice_scenes if scene["practice_variant"] == "reflect")
    assert {block["source_json_path"] for block in reflection_scene["component_blocks"]} == {
        "reflection.goal", "reflection.summary",
    }
    assert reflection_scene["title"] == "复盘与小结"
    assert [block["presentation_role"] for block in reflection_scene["component_blocks"]] == [
        "practice_reflection_goal", "practice_reflection_summary",
    ]
    prepare_scene = next(scene for scene in composed_practice_scenes if scene["practice_variant"] == "prepare")
    verify_scene = next(scene for scene in composed_practice_scenes if scene["practice_variant"] == "verify")
    assert [block["presentation_role"] for block in prepare_scene["component_blocks"]] == [
        "practice_phase_goal", "practice_phase_items",
    ]
    assert [block["presentation_role"] for block in verify_scene["component_blocks"]] == [
        "practice_phase_completion", "practice_phase_items",
    ]
    first_scene = next(scene for scene in scenes if scene["scene_id"] == next(item.scene_id for item in practice_scenes if item.practice_variant == "code"))
    assert first_scene["steps"] == []
    assert first_scene["component_blocks"][1]["component"] == "code_block"
    assert first_scene["component_blocks"][1]["code"] == "tool init"
    assert [block["source_json_path"] for block in first_scene["component_blocks"]] == [
        "practice.steps.step-1.instruction_text", "practice.steps.step-1.code_blocks.0",
        "practice.steps.step-1.verification",
    ]
    assert "旧 Markdown" not in "\n".join(first_scene["blocks"])
    assert validate_scene_shape(first_scene) == []
    rendered = render_courseware({"title": "结构化实操", "scenes": [first_scene]}).decode("utf-8")
    assert '<code data-language="bash">tool init</code>' in rendered
    assert 'data-source-json-path="practice.steps.step-1.instruction_text"' in rendered
    assert 'data-evidence-json-path="practice.steps.step-1.code_blocks.0.evidence_ids"' in rendered
    assert 'data-practice-json-step="true"' in rendered
    assert 'data-practice-verification' in rendered
    assert 'data-practice-verification-check' in rendered
    assert '<strong>完成验证：</strong>' in rendered
    assert '<strong>提示</strong>' not in rendered
    assert 'type="checkbox"' in rendered
    rendered_phases = render_courseware({"title": "结构化实操", "scenes": [prepare_scene, verify_scene]}).decode("utf-8")
    assert 'data-practice-json-phase="prepare"' in rendered_phases
    assert 'data-practice-phase-goal' in rendered_phases
    assert 'data-practice-json-phase="verify"' in rendered_phases
    assert 'data-practice-phase-items' in rendered_phases
    assert 'data-practice-phase-completion-check' in rendered_phases
    assert 'PREPARATION · SETUP' in rendered_phases
    assert 'VERIFICATION · CHECK' in rendered_phases
    assert 'PREPARATION ITEMS' in rendered_phases
    assert 'PHASE GOAL' in rendered_phases
    rendered_reflection = render_courseware({"title": "结构化实操", "scenes": [reflection_scene]}).decode("utf-8")
    assert 'data-practice-json-reflection="true"' in rendered_reflection
    assert 'data-practice-reflection-goal' in rendered_reflection
    assert 'data-practice-reflection-summary' in rendered_reflection
    assert '每一次认真复盘，都会让下一次实践更从容。' in rendered_reflection
    assert 'REFLECTION · WRAP-UP' in rendered_reflection


def test_practice_courseware_rejects_markdown_only_source():
    source = LearningResource(
        resource_id="guide-markdown", resource_type="实操指南", difficulty="初级",
        content_text="# 旧 Markdown", knowledge_points=["node"], source_refs=[],
    )

    with pytest.raises(CoursewareAdmissionError, match="V3"):
        _snapshot(source)


def test_courseware_admission_only_exposes_practice_and_review_sources():
    assert ROLE_BY_TYPE == {"实操指南": "practice", "复习清单": "checklist"}


def test_courseware_admission_rejects_other_learning_resource_types():
    source = SimpleNamespace(
        resource_id="lecture-1",
        learner_id="learner-1",
        publication_status="published",
        resource_type="讲义",
    )
    resource_service = SimpleNamespace(get=lambda resource_id: source if resource_id == source.resource_id else None)

    with pytest.raises(CoursewareAdmissionError, match="类型不受课件工作流支持"):
        admit_and_snapshot(
            resource_service,
            SimpleNamespace(get_run=lambda run_id: SimpleNamespace(knowledge_base_id="kb-1")),
            {"learner_id": "learner-1", "source_resource_ids": [source.resource_id]},
        )


def test_courseware_admission_accepts_review_checklist_source():
    source = LearningResource(
        resource_id="checklist-1",
        learner_id="learner-1",
        resource_type="复习清单",
        difficulty="初级",
        content_text="检索前先确认问题边界。",
        knowledge_points=["问题边界"],
        source_refs=[],
        publication_status="published",
        run_id="run-checklist-1",
    )
    snapshots, knowledge_base_id = admit_and_snapshot(
        SimpleNamespace(get=lambda resource_id: source if resource_id == source.resource_id else None),
        SimpleNamespace(get_run=lambda run_id: SimpleNamespace(knowledge_base_id="kb-1")),
        {"learner_id": "learner-1", "source_resource_ids": [source.resource_id]},
    )

    assert knowledge_base_id == "kb-1"
    assert snapshots[0]["role"] == "checklist"
