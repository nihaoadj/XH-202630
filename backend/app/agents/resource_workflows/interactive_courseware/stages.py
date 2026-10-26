"""Stage preparation and scene resolution, without job/checkpoint/release ownership."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from app.core.courseware.learning_design import build_learning_design
from app.models.courseware.learning_design import CoursewareLearningDesign
from app.models.courseware.snapshots import LearnerContextSnapshot
from app.agents.resource_workflows.interactive_courseware.validators import validate_storyboard_bindings


@dataclass(frozen=True)
class StageFailure:
    status: str
    code: str
    message: str
    event_stage: str
    event_status: str
    event_payload: dict[str, Any]


@dataclass(frozen=True)
class DesignStageResult:
    design: CoursewareLearningDesign | None = None
    warnings: list[dict[str, Any]] = field(default_factory=list)
    failure: StageFailure | None = None


@dataclass(frozen=True)
class SceneStageResult:
    scenes: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[dict[str, Any]] = field(default_factory=list)
    ai_enabled: bool = False
    failure: StageFailure | None = None


def prepare_design(
    snapshots: list[dict[str, Any]],
    learner_context: LearnerContextSnapshot,
    request_options: dict[str, Any],
) -> DesignStageResult:
    practice_step_structures: dict[str, list[dict[str, Any]]] = {}
    for source in snapshots:
        if source.get("role") != "practice":
            continue
        package = source.get("practice_guide_payload")
        if not isinstance(package, dict) or package.get("schema_version") != "3.0":
            code = "COURSEWARE_PRACTICE_JSON_REQUIRED"
            return DesignStageResult(failure=StageFailure(
                "rejected_admission", code,
                "实操课件必须使用已校验的 V3 固定阶段 JSON，禁止从 Markdown 拆分步骤",
                "practice_structure", "rejected", {"error_code": code},
            ))
        blocks_by_step = {
            str(block.get("practice_step_id")): str(block.get("block_id"))
            for block in source.get("blocks") or [] if block.get("practice_step_id") and block.get("block_id")
        }
        extracted = [
            {"title": str(step.get("title") or step["step_id"]), "source_block_ids": [blocks_by_step[str(step["step_id"])]]}
            for step in (package.get("practice") or {}).get("steps") or []
            if isinstance(step, dict) and str(step.get("step_id") or "") in blocks_by_step
        ]
        if not extracted:
            code = "COURSEWARE_PRACTICE_JSON_BINDING_INVALID"
            return DesignStageResult(failure=StageFailure(
                "quarantined", code, "实操指南 JSON 步骤无法与冻结来源块一一绑定",
                "practice_structure", "quarantined", {"error_code": code},
            ))
        practice_step_structures[str(source["resource_id"])] = extracted
    design = build_learning_design(snapshots, learner_context, request_options, practice_step_structures)
    warnings = [{
        "code": "ASSESSMENT_SCENE_OPTIONAL" if usage.get("unused_reason") == "missing_verifiable_exercise" else "COURSEWARE_RESOURCE_UNUSED",
        "message": f"资源 {usage['resource_id']} 未进入课程主线：{usage.get('unused_reason') or '未采用'}",
    } for usage in design.resource_usage_plan if usage.get("adopted") is False]
    return DesignStageResult(design=design, warnings=warnings)


def validate_scene_candidates(scenes: list[dict[str, Any]], design: CoursewareLearningDesign) -> StageFailure | None:
    design_payload = design.model_dump(mode="json")
    for candidate in scenes:
        errors = validate_storyboard_bindings(candidate, design_payload)
        if errors:
            code = "COURSEWARE_STORYBOARD_SLOT_MISMATCH"
            return StageFailure(
                "quarantined", code, "场景未严格填充冻结 Storyboard 槽位: " + ",".join(errors),
                "composing", "quarantined", {"error_code": code, "binding_errors": errors},
            )
    return None


def resolve_scene_candidates(
    scenes: list[dict[str, Any]],
    design: CoursewareLearningDesign,
    *,
    recovered_scenes: list[dict[str, Any]],
    ai_enabled: bool,
    compose_one: Callable,
    record_trace: Callable,
) -> SceneStageResult:
    """Resolve in stable input order; narrow callbacks retain existing budget/trace code."""
    if recovered_scenes:
        results = [(index, scene, None) for index, scene in enumerate(scenes)]
        ai_enabled = any((row.get("agent_version") or "").startswith("ai") for row in recovered_scenes)
    elif ai_enabled and len(scenes) > 1:
        with ThreadPoolExecutor(max_workers=min(2, len(scenes)), thread_name_prefix="courseware-scene") as executor:
            results = list(executor.map(lambda item: compose_one(*item), enumerate(scenes)))
    else:
        results = [compose_one(index, scene) for index, scene in enumerate(scenes)]
    enhanced_scenes: list[dict[str, Any] | None] = [None] * len(scenes)
    warnings = []
    hard_gate_code = None
    for index, resolved_scene, scene_warning in results:
        base_scene = scenes[index]
        scene_warning = record_trace(index, scene_warning)
        if scene_warning:
            warnings.append({**scene_warning, "scene_id": base_scene.get("scene_id")})
            if scene_warning.get("code") in {"AI_SCENE_UNKNOWN_COMPONENT", "AI_SCENE_UNKNOWN_SOURCE_BLOCK"}:
                hard_gate_code = scene_warning["code"]
        slot = list(design.storyboard.scenes)[index] if index < len(design.storyboard.scenes) else None
        if resolved_scene is not None:
            # Prose can enrich a slot, never mutate frozen source/component bindings.
            resolved_scene = {
                **resolved_scene,
                "scene_id": base_scene.get("scene_id") or (slot.scene_id if slot else None),
                "objective_ids": list(base_scene.get("objective_ids") or (slot.objective_ids if slot else [])),
                "allowed_component_ids": list(base_scene.get("allowed_component_ids") or (slot.allowed_component_ids if slot else [])),
                "source_refs": list(base_scene.get("source_refs") or []),
                "source_block_ids": list(base_scene.get("source_block_ids") or []),
            }
        enhanced_scenes[index] = resolved_scene
    failure = StageFailure(
        "quarantined", hard_gate_code, "AI 场景契约引用了未注册组件或未冻结来源块，未发布",
        "composing", "quarantined", {"error_code": hard_gate_code},
    ) if hard_gate_code else None
    return SceneStageResult(
        scenes=[scene for scene in enhanced_scenes if scene is not None],
        warnings=warnings, ai_enabled=ai_enabled, failure=failure,
    )
