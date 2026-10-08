"""LLM Agent that designs a source-scoped course outline."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.resource_workflows.interactive_courseware.contracts import (
    CoursewarePlanEnrichmentV2,
    ReviewPracticeCoursewarePlanEnrichment,
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
        review_source = next((item for item in snapshots if isinstance(item.get("review_practice_payload"), dict)
                              and item["review_practice_payload"].get("schema_version") == "2.0"), None)
        if review_source is not None and learning_design is not None:
            package = review_source["review_practice_payload"]
            node_ids = [str(item.get("skill_node_id")) for item in package.get("node_blocks") or []]
            result = llm_gateway.invoke_structured(
                messages=[
                    SystemMessage(content=(
                        "你只为主动回忆复习课件补充封面标题、封面导语和节点总结。"
                        "复习清单封面沿用编辑化的大标题、信息卡和完成提示的版式节奏，但使用独立的复习主题表达；"
                        "不要复制实操指南的措辞，不要输出颜色、CSS、HTML、JavaScript 或 URL。"
                        "course_title 应是简洁、适合封面展示的复习清单标题；overview_lead 应用 1—2 句说明"
                        "先闭卷回忆、再概念辨析、再进行正反例辨认并完成自评。"
                        "learning_scope 用 1—2 句说明本轮实际覆盖的学习节点、能力或证据范围；"
                        "learning_method 用 1—2 句说明如何使用课件：先独立回忆，再揭示答案、自评并回到证据复核。"
                        "这两个字段会渲染为封面信息卡，文字应短而具体，不要输出列表、颜色、CSS、HTML 或组件名。"
                        "completion_lead 应是结尾页的完成检查引导，completion_message 应是 1—2 句可执行的结语："
                        "根据学习者的会/模糊/不会自评，说明何时回到节点复习、何时进入实操或分阶测试；"
                        "overall_summary 应是结尾页中间主卡的整体复盘，写 2—4 句，串联本轮覆盖的节点、"
                        "闭卷回忆、概念辨析、正反例辨认三种练习，以及学习者接下来应关注的证据边界；"
                        "只能依据输入的节点与复习结构，不得虚构掌握率、成绩或未提供的事实。"
                        "不得声称学习者已经掌握，也不得虚构成绩。"
                        "题目、答案、Evidence、组件、页面顺序和每页题量全部由平台冻结；不得输出或改写它们。"
                        "每个节点总结只说明本节点应如何依据题目与证据复盘。"
                    )),
                    HumanMessage(content=json.dumps({
                        "topic": review_source.get("topic"), "title": package.get("title"),
                        "node_ids": node_ids,
                        "page_design": {
                            "recall": "闭卷回忆：2页，每页2题",
                            "distinction": "概念辨析：2页，每页2题",
                            "example_recognition": "正反例辨认：1页，2题",
                            "completion": "结尾页：节点完成检查、自评提示和下一步建议",
                            "overall_summary": "结尾页中间区域：模型生成整体复盘主卡，串联节点、练习方法和下一步关注点",
                            "overview_cards": "封面信息卡：学习范围、学习方法、节点复习路径",
                        },
                        "nodes": [{
                            "skill_node_id": item.get("skill_node_id"),
                            "skill_node_name": item.get("skill_node_name"),
                            "question_count": len(item.get("recall_questions") or [])
                            + len(item.get("distinction_questions") or [])
                            + len(item.get("example_recognition_questions") or [])
                            + (1 if not item.get("example_recognition_questions") and item.get("example_recognition") else 0),
                        } for item in package.get("node_blocks") or []],
                    }, ensure_ascii=False)),
                ], output_schema=ReviewPracticeCoursewarePlanEnrichment,
                context=LLMCallContext(run_id=run_id, step_id=f"{run_id}:review-practice-enrichment", node_name="courseware_review_practice_enricher", schema_name="ReviewPracticeCoursewarePlanEnrichment"),
                options=allowance or llm_gateway.options_for("generator", temperature=0.0),
            )
            if any(item.skill_node_id not in set(node_ids) for item in result.output.node_summaries):
                raise ValueError("未知 review node ID")
            spec, _, _ = _platform_spec(learning_design, snapshots)
            spec.title = result.output.course_title.strip()
            spec.review_practice_enrichment = result.output
            trace_method = getattr(result, "trace_metadata", None)
            trace = trace_method() if callable(trace_method) else {}
            return spec, ({"code": "LLM_TRACE", "node_name": "courseware_review_practice_enricher", "trace": trace} if trace else None)
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
                    "如果输入包含 schema_version=3.0 的实操指南，必须额外填写 practice_cover："
                    "cover_title 生成简洁、适合大标题展示的实操课件标题，不要带‘互动课件’、页码或长段落；"
                    "cover_lead 用一句话说明这份实操指南解决的实际任务；"
                    "learning_goal 用一句话说明完成这份实操指南后应具备的可观察能力；"
                    "learning_method 用一段简短说明介绍本指南的使用方法，例如先阅读每页的操作说明、"
                    "再实际执行并用完成验证核对结果；不要输出编号步骤、清单或路径；"
                    "completion_standard 说明什么结果才算完成。"
                    "这些内容只能概括输入的实操 JSON，不得虚构工具、步骤、指标或学习结果。"
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
                    "practice_guides": [
                        {
                            "resource_id": item["resource_id"],
                            "topic": item.get("topic"),
                            "practice_guide_payload": item.get("practice_guide_payload"),
                        }
                        for item in snapshots
                        if item.get("role") == "practice"
                        and isinstance(item.get("practice_guide_payload"), dict)
                        and item["practice_guide_payload"].get("schema_version") == "3.0"
                    ],
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
            has_structured_practice = any(
                item.get("role") == "practice"
                and isinstance(item.get("practice_guide_payload"), dict)
                and item["practice_guide_payload"].get("schema_version") == "3.0"
                for item in snapshots
            )
            if has_structured_practice and result.output.practice_cover is None:
                raise ValueError("实操指南规划缺少 practice_cover")
            spec, scene_ids, objective_ids = _platform_spec(learning_design, snapshots)
            # ``merge_plan_enrichment`` deliberately applies only the platform
            # owned title/objective/slot projections to ``spec``.  Keep the
            # original planner payload as well: the practice cover fields are
            # renderer-safe prose consumed later by deterministic composition.
            # Without this assignment they were validated successfully here,
            # then silently discarded before the spec was persisted.
            enrichment = result.output
            spec = merge_plan_enrichment(
                spec,
                enrichment,
                scene_ids=scene_ids,
                objective_ids=objective_ids,
            )
            spec.enrichment = enrichment
            result.output = spec
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
