"""LLM Agent that designs a source-scoped course outline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewarePlanEnrichmentV2,
    CoursewareScenePlan,
    CoursewareSpec,
)
from app.core.courseware.components import is_registered_component
from app.agents.resource_workflows.interactive_courseware.runtime import courseware_ai_available
from app.core.llm.gateway import LLMGateway, LLMGatewayError
from app.models.shared.llm import LLMCallContext
from app.models.shared.llm import LLMCallOptions
from app.models.courseware.learning_design import CoursewareLearningDesign


def _platform_spec(
    learning_design: CoursewareLearningDesign,
    snapshots: list[dict[str, Any]],
) -> tuple[CoursewareSpec, list[str], list[str]]:
    """Build immutable source/slot bindings before asking for model prose."""

    sources = {str(item["resource_id"]): item for item in snapshots}
    first_source_id = next(iter(sources), "")
    all_source_blocks = {
        str(block["block_id"])
        for source in sources.values()
        for block in source.get("blocks", [])
        if block.get("block_id")
    } | {
        str(value)
        for source in sources.values()
        for value in source.get("source_block_ids") or []
    }
    scenes: list[CoursewareScenePlan] = []
    scene_ids: list[str] = []
    for slot in learning_design.storyboard.scenes:
        if slot.kind == "recap":
            continue
        source_id = str(slot.source_resource_ids[0]) if slot.source_resource_ids else first_source_id
        if source_id not in sources:
            raise ValueError("Storyboard 引用了未冻结资源")
        source_blocks = {
            str(block["block_id"]) for block in sources[source_id].get("blocks", []) if block.get("block_id")
        } | {str(value) for value in sources[source_id].get("source_block_ids") or []}
        multi_source = len(slot.source_resource_ids) > 1
        block_ids = list(slot.source_block_ids) or sorted(
            all_source_blocks if slot.kind == "compare" or multi_source else source_blocks
        )
        allowed_blocks = all_source_blocks if slot.kind == "compare" or multi_source else source_blocks
        if not block_ids or not set(block_ids).issubset(allowed_blocks):
            raise ValueError("Storyboard 引用了未冻结来源块")
        scenes.append(CoursewareScenePlan(
            source_resource_id=source_id,
            kind=slot.kind,
            title=slot.scene_id,
            learning_objective=slot.interaction_purpose,
            source_block_ids=block_ids,
            preferred_component_ids=list(slot.allowed_component_ids),
            required=slot.required,
            page_role=slot.page_role, layout_recipe_id=slot.layout_recipe_id,
            key_question=slot.key_question, required_zones=list(slot.required_zones),
            content_budget=slot.content_budget,
        ))
        scene_ids.append(str(slot.scene_id))
    objective_ids = [str(item.objective_id) for item in learning_design.objectives.objectives]
    objectives = [item.statement for item in learning_design.objectives.objectives]
    topic = next((str(item.get("topic") or "").strip() for item in snapshots if item.get("topic")), "互动课件")
    return CoursewareSpec(title=topic, learning_objectives=objectives, scenes=scenes), scene_ids, objective_ids


def merge_plan_enrichment(
    spec: CoursewareSpec,
    enrichment,
    *,
    scene_ids: list[str],
    objective_ids: list[str] | None = None,
) -> CoursewareSpec:
    """Apply optional model prose by platform-owned IDs.

    The platform's storyboard remains authoritative: missing enrichment keeps
    the deterministic value, and array order has no semantic meaning.
    """
    known_scenes = set(scene_ids)
    for item in enrichment.scenes:
        if item.scene_id not in known_scenes:
            raise ValueError(f"未知 scene_id: {item.scene_id}")
        for component_id in item.preferred_component_ids:
            if not any(is_registered_component(component_id, version) for version in ("1.0", "2.0", "3.0")):
                raise ValueError(f"未注册组件: {component_id}")
    known_objectives = set(objective_ids or [])
    for item in enrichment.objectives:
        if objective_ids is not None and item.objective_id not in known_objectives:
            raise ValueError(f"未知 objective_id: {item.objective_id}")
    scene_by_id = {scene_id: item for scene_id, item in zip(scene_ids, spec.scenes)}
    updates = {item.scene_id: item for item in enrichment.scenes}
    for scene_id, item in updates.items():
        target = scene_by_id[scene_id]
        target.title = item.title
        target.learning_objective = item.teaching_intent
        target.preferred_component_ids = list(item.preferred_component_ids)
    if objective_ids is not None:
        objective_by_id = {item.objective_id: item for item in enrichment.objectives}
        spec.learning_objectives = [
            objective_by_id.get(objective_id).title if objective_id in objective_by_id else value
            for objective_id, value in zip(objective_ids, spec.learning_objectives)
        ]
    if enrichment.course_title.strip():
        spec.title = enrichment.course_title.strip()
    return spec


def build_courseware_spec(
    llm_gateway: LLMGateway | None, run_id: str, snapshots: list[dict[str, Any]],
    *, allowance: LLMCallOptions | None = None,
    learning_design: CoursewareLearningDesign | None = None,
    request_options: dict[str, Any] | None = None,
) -> tuple[CoursewareSpec | None, dict[str, Any] | None]:
    if not courseware_ai_available(llm_gateway):
        return None, None
    try:
        provider_schema = CoursewarePlanEnrichmentV2 if learning_design is not None else CoursewareSpec
        enrichment_contract = None
        if learning_design is not None:
            enrichable_scenes = [
                item for item in learning_design.storyboard.scenes if item.kind != "recap"
            ]
            enrichment_contract = {
                "objective_ids": [str(item.objective_id) for item in learning_design.objectives.objectives],
                "scene_ids": [str(item.scene_id) for item in enrichable_scenes],
                "allowed_component_ids_by_scene": {
                    str(item.scene_id): list(item.allowed_component_ids) for item in enrichable_scenes
                },
            }
        result = llm_gateway.invoke_structured(
            messages=[
                SystemMessage(content=(
                    "你是课程设计器。不得写学习者正文、不得新增事实、不得输出 HTML、CSS、JavaScript 或 URL。"
                    "当输入含 Storyboard 时，只输出 CoursewarePlanEnrichmentV2：按给定 objective_id 和 scene_id"
                    "补充标题、教学意图和已注册组件偏好；不得重新生成、删除、重排或改写来源槽位。"
                    "只能使用 plan_enrichment_contract 中列出的 ID 与对应场景允许的组件；"
                    "recap 不接受 enrichment。数组顺序不重要，未知 ID 和未知组件会被拒绝。"
                )),
                HumanMessage(content=json.dumps({
                    "sources": [
                        {"resource_id": item["resource_id"], "role": item["role"], "topic": item["topic"],
                         "source_block_ids": [block["block_id"] for block in item.get("blocks", [])]
                         or list(item.get("source_block_ids") or [])}
                        for item in snapshots
                    ],
                    "storyboard": learning_design.storyboard.model_dump(mode="json") if learning_design else None,
                    "plan_enrichment_contract": enrichment_contract,
                    "learner_request": request_options or {},
                }, ensure_ascii=False)),
            ],
            output_schema=provider_schema,
            context=LLMCallContext(
                run_id=run_id, step_id=f"{run_id}:courseware-spec",
                node_name="courseware_spec_builder", schema_name=provider_schema.__name__,
            ),
            options=allowance or llm_gateway.options_for("generator", temperature=0.0),
        )
        if learning_design is not None:
            spec, scene_ids, objective_ids = _platform_spec(learning_design, snapshots)
            result.output = merge_plan_enrichment(
                spec,
                result.output,
                scene_ids=scene_ids,
                objective_ids=objective_ids,
            )
        allowed = {item["resource_id"] for item in snapshots}
        allowed_blocks = {
            item["resource_id"]: {
                block["block_id"] for block in item.get("blocks", [])
            } | {str(block_id) for block_id in (item.get("source_block_ids") or [])}
            for item in snapshots
        }
        if any(scene.source_resource_id not in allowed for scene in result.output.scenes):
            raise ValueError("AI 课程规格引用了未冻结资源")
        all_frozen_blocks = set().union(*allowed_blocks.values()) if allowed_blocks else set()
        if any(
            not set(scene.source_block_ids).issubset(
                all_frozen_blocks if scene.kind == "compare" or scene.page_role == "learning_map"
                else allowed_blocks[scene.source_resource_id]
            )
            for scene in result.output.scenes
        ):
            raise ValueError("AI 课程规格引用了未冻结来源块")
        if learning_design is None and result.output.enrichment:
            objective_ids = [
                str(item.objective_id)
                for item in (learning_design.objectives.objectives if learning_design else ())
            ]
            scene_ids = [str(item.scene_id) for item in (learning_design.storyboard.scenes if learning_design else ())]
            if any(item.objective_id not in set(objective_ids) for item in result.output.enrichment.objectives):
                raise ValueError("AI enrichment 引用了未知 objective_id")
            if any(item.scene_id not in set(scene_ids) for item in result.output.enrichment.scenes):
                raise ValueError("AI enrichment 引用了未知 scene_id")
            if any(not any(is_registered_component(component, version) for version in ("1.0", "2.0", "3.0"))
                   for item in result.output.enrichment.scenes for component in item.preferred_component_ids):
                raise ValueError("AI enrichment 引用了未注册组件")
            result.output = merge_plan_enrichment(
                result.output,
                result.output.enrichment,
                scene_ids=scene_ids,
                objective_ids=objective_ids,
            )
        trace_method = getattr(result, "trace_metadata", None)
        trace = trace_method() if callable(trace_method) else {}
        if not trace:
            return result.output, None
        return result.output, {
            "code": "LLM_TRACE",
            "node_name": "courseware_spec_builder",
            "trace": trace,
        }
    except (LLMGatewayError, ValueError) as exc:
        code = "AI_PLAN_ENRICHMENT_REJECTED" if "enrichment" in str(exc) or "未知 " in str(exc) or "未注册组件" in str(exc) else "AI_PLAN_FALLBACK"
        return None, {
            "code": code,
            "message": "AI enrichment candidate 未通过稳定 ID/组件校验，已保留平台确定性设计" if code == "AI_PLAN_ENRICHMENT_REJECTED" else "AI 课程设计不可用，已降级为确定性编排",
            "failure_type": type(exc).__name__,
            "failure_code": getattr(exc, "code", None),
            "failure_detail": str(exc)[:160] if isinstance(exc, ValueError) else None,
        }
