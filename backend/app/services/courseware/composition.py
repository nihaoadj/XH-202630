"""Deterministic scene composition for the courseware service."""

import re
from typing import Any

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSpec
from app.models.courseware.learning_design import CoursewareLearningDesign


def _paragraphs(content: str) -> list[str]:
    if content.strip().startswith("```"):
        return [content.strip()]
    lines = [part.strip(" #-\t") for part in content.split("\n") if part.strip()]
    parts = [
        sentence.strip()
        for line in lines
        for sentence in re.split(r"(?<=[。！？；])\s*", line)
        if sentence.strip()
    ]
    return parts[:12] or ["源资源内容为空。"]


def _steps(content: str) -> list[str]:
    values = [part.strip(" #-*0123456789.、\t") for part in content.split("\n") if part.strip()]
    return [item for item in values if item][:8] or ["阅读实操指南并完成关键步骤。"]


def _practice_step_title(scene_id: str, source_parts: list[str], key_question: str = "") -> str:
    match = re.search(r":step:(\d+)(?::part:(\d+))?$", scene_id)
    number = int(match.group(1)) if match else 1
    part = int(match.group(2)) if match and match.group(2) else 1
    raw = source_parts[0] if source_parts else "完成本步操作"
    # The second page of a dense step can legitimately begin with a fenced
    # code block.  Its heading must still name the parent operation rather
    # than exposing the first line of source code as a page title.
    if raw.lstrip().startswith("```"):
        label = re.search(r"[：:]\s*(.+?)\s+应如何完成", key_question)
        raw = label.group(1) if label else "继续完成本步骤"
    raw = re.sub(r"^\s*(?:#{1,6}\s*)?(?:第\s*)?(?:步骤\s*)?(?:\d+|[一二三四五六七八九十]+)\s*(?:[、.．:：)）]|\s+-\s+)", "", raw).strip()
    suffix = f"｜第 {part} 段说明" if match and match.group(2) else ""
    return f"步骤 {number}{suffix}｜{(raw or '完成本步操作')[:42]}"


def _quiz(source: dict[str, Any]) -> dict[str, Any] | None:
    for item in source.get("exercise_items", []):
        options = item.get("options") or []
        answer = item.get("answer")
        if options and isinstance(answer, (str, list)):
            answer_values = answer if isinstance(answer, list) else [answer]
            source_block_ids = [block["block_id"] for block in source.get("blocks", [])[:1]]
            return {
                "kind": "quiz", "title": "自测", "blocks": [item.get("question") or "请选择正确答案。"],
                "options": [str(option) for option in options], "answer": [str(value) for value in answer_values],
                "feedback": str(item.get("explanation") or "根据冻结来源复盘后重试。"),
                "source_refs": [source["resource_id"]], "source_block_ids": source_block_ids,
                "source_map": {"title": [source_block_ids[:1]], "blocks": [source_block_ids],
                               "options": [source_block_ids for _ in options], "answer": [source_block_ids],
                               "feedback": [source_block_ids]},
            }
    return None


def _component_block(scene: dict[str, Any], component: str, source_block_ids: list[str]) -> dict[str, Any]:
    source_id = (scene.get("source_refs") or ["source"])[0]
    refs = [{"source_resource_id": source_id, "source_block_ids": source_block_ids or ["block-1"]}]
    block = {"schema_version": "1.0", "block_id": f"{scene.get('scene_id') or scene.get('kind')}-{component}", "component": component,
             "text": str((scene.get("blocks") or ["学习内容"])[0]), "source_refs": refs}
    if component == "flashcard":
        block.update({"front": str((scene.get("blocks") or ["问题"])[0]), "back": str((scene.get("blocks") or ["根据来源复盘。"])[-1])})
    if component == "steps":
        block["text"] = "请按来源步骤完成练习。"
    if component == "compare":
        block["text"] = "并列比较冻结来源中的关键观点。"
    return block


def _decorate_components(scenes: list[dict[str, Any]]) -> None:
    for scene in scenes:
        if scene.get("component_blocks"):
            continue
        allowed = list(scene.get("allowed_component_ids") or scene.get("allowed_components") or [])
        component = {
            "intro": "callout", "explain": "key_point", "example": "flashcard", "compare": "compare",
            "practice": "steps", "quiz": "single_choice", "recap": "recap",
        }.get(scene.get("kind"), allowed[0] if allowed else "callout")
        if component not in allowed and allowed:
            component = allowed[0]
        scene["component_blocks"] = [_component_block(scene, component, list(scene.get("source_block_ids") or []))]


def _compose_blueprint_scenes(
    snapshots: list[dict[str, Any]], learning_design: CoursewareLearningDesign,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fill v3 storyboard slots without inventing pages or copying a source in a loop."""

    adopted_ids = {item["resource_id"] for item in learning_design.resource_usage_plan if item.get("adopted", True)}
    by_id = {item["resource_id"]: item for item in snapshots if item["resource_id"] in adopted_ids}
    title_by_role = {
        "cover": "课程导览", "learning_map": "学习地图", "concept_explanation": "核心概念",
        "process_breakdown": "流程拆解", "case_diagnosis": "案例诊断",
        "comparison_analysis": "对比分析", "practice_workspace": "实践工作台",
        "knowledge_check": "知识检查", "summary_action": "总结与行动",
    }
    component_by_role = {
        "cover": ("callout", "key_point"), "learning_map": ("steps", "key_point", "callout"),
        "concept_explanation": ("key_point", "callout", "compare"),
        "process_breakdown": ("steps", "key_point", "callout"),
        "case_diagnosis": ("callout", "compare", "key_point"),
        "comparison_analysis": ("compare", "key_point", "callout"),
        "practice_workspace": ("steps", "key_point", "callout"),
        "knowledge_check": ("single_choice", "callout"),
        "summary_action": ("recap", "key_point", "callout"),
    }
    scenes: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    final_practice_scene_ids = {
        slot.scene_id
        for slot in learning_design.storyboard.scenes
        if slot.kind == "practice"
        and not any(
            other.kind == "practice"
            and other.scene_id.startswith(slot.scene_id.rsplit(":part:", 1)[0] + ":part:")
            and other.scene_id > slot.scene_id
            for other in learning_design.storyboard.scenes
        )
    }
    for slot in learning_design.storyboard.scenes:
        sources = [by_id[rid] for rid in slot.source_resource_ids if rid in by_id]
        if not sources:
            warnings.append({"code": "SCENE_SKIPPED", "message": f"{slot.scene_id} 缺少冻结来源，已阻止空页"})
            continue
        source_ids = [str(source["resource_id"]) for source in sources]
        allowed_block_ids = set(slot.source_block_ids)
        selected_blocks = [
            (source, block) for source in sources for block in (source.get("blocks") or [])
            if block.get("block_id") and (not allowed_block_ids or block["block_id"] in allowed_block_ids)
        ]
        block_owner = {str(block["block_id"]): str(source["resource_id"]) for source, block in selected_blocks}
        block_ids = [str(block["block_id"]) for _, block in selected_blocks]
        content_parts = [str(block.get("text") or "").strip() for _, block in selected_blocks if str(block.get("text") or "").strip()]
        if not content_parts:
            content_parts = [part for source in sources for part in _paragraphs(str(source.get("content") or ""))]
        max_source_parts = 18 if slot.kind == "practice" else 10
        content_parts = [part for text in content_parts for part in _paragraphs(text) if part][:max_source_parts]
        if not content_parts:
            warnings.append({"code": "EMPTY_PAGE", "message": f"{slot.scene_id} 无有效来源内容，已阻止空页"})
            continue
        source_content_parts = list(content_parts)
        role = slot.page_role or {
            "intro": "cover", "compare": "comparison_analysis", "practice": "practice_workspace",
            "quiz": "knowledge_check", "recap": "summary_action",
        }.get(slot.kind, "concept_explanation")
        recipe = slot.layout_recipe_id or {
            "cover": "editorial_cover", "comparison_analysis": "comparison_matrix",
            "practice_workspace": "practice_workspace", "knowledge_check": "quiz_focus",
            "summary_action": "recap_dashboard",
        }.get(role, "concept_split")
        # A short source paragraph still needs a complete learning page.  Add
        # source-bound instructional zones (goal, method and completion) so
        # deterministic fallback is useful and passes the same page-quality
        # gate as an AI-composed page.  These phrases add no domain facts.
        if role == "cover":
            display_parts = [
                f"学习范围：{source_content_parts[0]}",
                "学习方法：围绕这份冻结资源阅读关键内容，并在互动中主动检查自己的理解。",
                "完成信号：能够依据资源说明核心要点，并知道下一步应继续练习还是复习。",
            ]
        elif role == "practice_workspace":
            # ``block_ids`` has already been bounded to one page-sized segment
            # by the learning design.  Keep every block in that segment here:
            # truncating to four paragraphs silently discarded the latter half
            # of a detailed operation, which is exactly the information a
            # learner needs to finish the current step.
            detail = "\n\n".join(source_content_parts)
            display_parts = [
                f"本步目标：{source_content_parts[0]}",
                f"操作说明：{detail}",
                "完成校验：对照本页来源逐项核对输入、操作结果和预期状态；不满足时在本步修正后再继续。",
                "衔接提示：确认本步已经完成并勾选，再进入下一步；不要把后续步骤提前混入本页。",
            ]
        elif role == "knowledge_check":
            display_parts = [
                f"作答依据：{source_content_parts[0]}",
                "请先独立作答，再结合解析回到冻结资源定位判断依据，而不是只记住选项。",
                "完成后把错误原因转化为下一次作答时可执行的检查问题。",
            ]
        elif role == "summary_action":
            display_parts = [
                f"本资源回顾：{source_content_parts[0]}",
                "请用自己的话复述关键要点，并标记仍需要回看来源或重新练习的部分。",
                "下一步行动：根据本次互动结果选择继续实操、重新答题或回到资源复习。",
            ]
        elif role == "case_diagnosis":
            display_parts = [
                f"案例背景：{source_content_parts[0]}",
                "问题定位：先区分案例中已经给出的事实、需要判断的关键问题，以及不能由来源证明的假设。",
                "证据判断：把每个结论回连到冻结资源的具体描述，避免仅凭经验快速下结论。",
                "行动建议：基于已确认的证据选择下一步诊断或处理动作，并说明该动作为什么适合当前情境。",
            ]
        elif role == "concept_explanation":
            display_parts = [
                f"核心概念：{source_content_parts[0]}",
                "理解路径：先辨认概念的对象、作用和边界，再把它与资源中的具体描述建立对应关系。",
                "应用提示：遇到相近概念时，使用来源中的条件与证据进行区分，不凭关键词直接判断。",
                "自我检查：尝试用自己的话解释这一概念，并指出可以回到资源核验的依据。",
            ]
        else:
            display_parts = source_content_parts[:4]
        scene = {
            "scene_id": slot.scene_id, "kind": slot.kind, "page_role": role,
            "layout_recipe_id": recipe, "key_question": slot.key_question,
            "practice_variant": slot.practice_variant,
            "required_zones": list(slot.required_zones), "content_budget": slot.content_budget.model_dump(mode="json"),
            "title": (
                _practice_step_title(slot.scene_id, source_content_parts, slot.key_question or "")
                if slot.kind == "practice" and ":step:" in slot.scene_id
                else title_by_role.get(role, slot.interaction_purpose)
            ),
            "lead": (
                f"本页聚焦“{slot.key_question or slot.interaction_purpose}”。"
                "请带着问题阅读来源信息，并观察概念、证据与行动之间的联系。"
            ),
            "blocks": display_parts[:4],
            "conclusion": (
                f"页面结论：{source_content_parts[-1]}"
                "下一步请把本页判断带入后续场景，通过操作或检查验证理解。"
            ),
            "source_refs": source_ids, "source_block_ids": block_ids,
            "objective_ids": list(slot.objective_ids), "allowed_component_ids": list(slot.allowed_component_ids),
            "source_map": {
                "title": [block_ids[:1]], "lead": [block_ids[:1]],
                "blocks": [[block_ids[min(index, len(block_ids) - 1)]] if block_ids else [] for index in range(min(4, len(display_parts)))],
                "conclusion": [block_ids[-1:] if block_ids else []],
            },
        }
        if slot.kind == "practice":
            # One page represents one source-guide step.  The detailed source
            # remains in the explanatory zones; the checklist has exactly one
            # completion action so it cannot be mistaken for a summary page.
            # Only the final segment of a dense real-world step may mark the
            # operation as complete. Earlier segments are detailed guidance.
            is_final_part = slot.scene_id in final_practice_scene_ids
            # The page title already identifies the operation. Repeating that
            # full title inside the checkbox wastes the limited practice
            # workspace and makes the interaction look like another heading.
            scene["steps"] = [
                "我已核对本段内容，继续阅读同一步骤的下一段"
                if not is_final_part else "我已完成本步骤并核对预期结果"
            ]
            scene["source_map"]["steps"] = [block_ids[:1] if block_ids else []]
        if slot.kind == "quiz":
            quiz = next((_quiz(source) for source in sources if source.get("role") == "assessment"), None)
            if quiz:
                scene.update({key: quiz[key] for key in ("blocks", "options", "answer", "feedback")})
                scene["source_map"].update(quiz["source_map"])
            else:
                warnings.append({"code": "ASSESSMENT_SCENE_SKIPPED", "message": "知识检查页缺少可验证答案，已阻止发布空壳测验"})
                continue
        preferred = tuple(slot.allowed_component_ids or slot.allowed_components) or component_by_role.get(role, ("callout", "key_point"))
        scene["component_blocks"] = []
        for index, text in enumerate(scene["blocks"][:4]):
            component = preferred[min(index, len(preferred) - 1)]
            component_block = {
                "schema_version": "1.0", "block_id": f"{slot.scene_id}:zone-{index + 1}",
                "component": component, "text": text,
                "pedagogical_role": "recap" if role == "summary_action" else ("example" if index == 2 else "explain"),
                "source_refs": [{
                    "source_resource_id": block_owner.get(
                        block_ids[min(index, len(block_ids) - 1)] if block_ids else "", source_ids[0]
                    ),
                    "source_block_ids": [block_ids[min(index, len(block_ids) - 1)]] if block_ids else list(slot.source_block_ids[:1]),
                }],
            }
            if component in {"steps", "ordered_steps"}:
                component_block["steps"] = list(scene.get("steps") or content_parts[:6])
            scene["component_blocks"].append(component_block)
        scenes.append(scene)
    return scenes, warnings


def compose_scenes(
    snapshots: list[dict[str, Any]], plan: CoursewareSpec | None = None,
    *, learning_design: CoursewareLearningDesign | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    if learning_design and learning_design.schema_version == "3.0":
        return _compose_blueprint_scenes(snapshots, learning_design)
    scenes: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    if learning_design:
        adopted_ids = {item["resource_id"] for item in learning_design.resource_usage_plan if item.get("adopted", True)}
        adopted_snapshots = [item for item in snapshots if item["resource_id"] in adopted_ids]
    else:
        adopted_snapshots = list(snapshots)
    by_id = {item["resource_id"]: item for item in adopted_snapshots}
    storyboard = list(learning_design.storyboard.scenes) if learning_design else []
    storyboard_by_kind_source = {(item.kind, item.source_resource_ids[0] if item.source_resource_ids else None): item for item in storyboard}
    ordered_sources = [
        (by_id[item.source_resource_id], item)
        for item in plan.scenes
        if item.source_resource_id in by_id
    ] if plan else [(source, None) for source in adopted_snapshots]
    for source, planned_scene in ordered_sources:
        try:
            target_kind = planned_scene.kind if planned_scene else None
            if source["role"] in {"lecture", "case_study"} and source["content"]:
                kind = target_kind or ("intro" if not scenes else "explain")
                source_block_ids = [item["block_id"] for item in source.get("blocks", [])[:8]]
                scene = {
                    "kind": kind, "title": "学习目标" if kind == "intro" else source["resource_type"],
                    "blocks": _paragraphs(source["content"]), "source_refs": [source["resource_id"]],
                    "source_block_ids": source_block_ids,
                    "source_map": {"title": [source_block_ids[:1]], "blocks": [[block_id] for block_id in source_block_ids]},
                }
                slot = storyboard_by_kind_source.get((kind, source["resource_id"]))
                if slot:
                    scene.update({"scene_id": slot.scene_id, "objective_ids": list(slot.objective_ids),
                                  "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components),
                                  "source_block_ids": [x for x in source_block_ids if x in slot.source_block_ids] or list(slot.source_block_ids)})
                scenes.append(scene)
            elif source["role"] == "practice" and source["content"]:
                steps = _steps(source["content"])
                source_block_ids = [item["block_id"] for item in source.get("blocks", [])[:8]]
                scene = {
                    "kind": target_kind or "practice", "title": "动手练习",
                    "blocks": ["请按步骤完成练习，并勾选已完成项。"], "steps": steps,
                    "source_refs": [source["resource_id"]], "source_block_ids": source_block_ids,
                    "source_map": {"title": [source_block_ids[:1]], "blocks": [source_block_ids],
                                   "steps": [[block_id] for block_id in source_block_ids[:len(steps)]]},
                }
                slot = storyboard_by_kind_source.get((scene["kind"], source["resource_id"]))
                if slot:
                    scene.update({"scene_id": slot.scene_id, "objective_ids": list(slot.objective_ids),
                                  "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components),
                                  "source_block_ids": [x for x in source_block_ids if x in slot.source_block_ids] or list(slot.source_block_ids)})
                scenes.append(scene)
            elif source["role"] == "assessment":
                quiz = _quiz(source)
                if quiz and (target_kind or "quiz") == "quiz":
                    slot = storyboard_by_kind_source.get(("quiz", source["resource_id"]))
                    if slot:
                        quiz.update({"scene_id": slot.scene_id, "objective_ids": list(slot.objective_ids),
                                     "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components),
                                     "source_block_ids": [x for x in quiz["source_block_ids"] if x in slot.source_block_ids] or list(slot.source_block_ids)})
                    scenes.append(quiz)
                elif target_kind:
                    source_block_ids = [item["block_id"] for item in source.get("blocks", [])[:8]]
                    scene = {
                        "kind": target_kind, "title": "基于测试题的学习活动",
                        "blocks": _paragraphs(str(source.get("content") or "自测材料")),
                        "source_refs": [source["resource_id"]], "source_block_ids": source_block_ids,
                        "source_map": {"title": [source_block_ids[:1]], "blocks": [source_block_ids]},
                    }
                    slot = storyboard_by_kind_source.get((target_kind, source["resource_id"]))
                    if slot:
                        scene.update({"scene_id": slot.scene_id, "objective_ids": list(slot.objective_ids),
                                      "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components),
                                      "source_block_ids": [x for x in source_block_ids if x in slot.source_block_ids] or list(slot.source_block_ids)})
                    scenes.append(scene)
                else:
                    warnings.append({"code": "ASSESSMENT_SCENE_SKIPPED", "message": "测试题缺少可安全映射的客观题，已跳过自测场景"})
        except Exception:
            warnings.append({"code": "SCENE_SKIPPED", "message": f"{source['resource_type']} 场景生成失败，其他场景继续发布"})
    if learning_design:
        existing = {str(item.get("scene_id")) for item in scenes if item.get("scene_id")}
        for slot in learning_design.storyboard.scenes:
            if slot.kind == "recap" or slot.scene_id in existing:
                continue
            source_rows = [by_id[rid] for rid in slot.source_resource_ids if rid in by_id]
            if not source_rows:
                continue
            source_block_ids = [str(block.get("block_id")) for row in source_rows for block in (row.get("blocks") or [])[:1] if block.get("block_id")]
            scene = {
                "scene_id": slot.scene_id, "kind": slot.kind, "title": slot.interaction_purpose,
                "blocks": ["请结合冻结来源完成本场景。"], "source_refs": [row["resource_id"] for row in source_rows],
                "source_block_ids": source_block_ids, "objective_ids": list(slot.objective_ids),
                "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components),
                "source_map": {"title": [source_block_ids[:1]], "blocks": [source_block_ids]},
            }
            if slot.kind == "practice":
                scene["steps"] = _steps(str(source_rows[0].get("content") or ""))
            scenes.append(scene)
    points = [point for item in snapshots for point in item.get("knowledge_points", [])][:8]
    recap_block_ids = [block["block_id"] for item in adopted_snapshots for block in item.get("blocks", [])[:1]]
    recap = {
        "kind": "recap", "title": "复盘",
        "blocks": ["本课件已完成。请回顾以下知识点：", "、".join(points) or "请回顾本节的核心内容。"],
        "source_refs": [item["resource_id"] for item in adopted_snapshots],
        "source_block_ids": recap_block_ids,
        "source_map": {"title": [recap_block_ids[:1]], "blocks": [recap_block_ids, recap_block_ids]},
    }
    slot = storyboard_by_kind_source.get(("recap", None)) or next((item for item in storyboard if item.kind == "recap"), None)
    if slot:
        recap.update({"scene_id": slot.scene_id, "objective_ids": list(slot.objective_ids),
                      "allowed_component_ids": list(slot.allowed_component_ids or slot.allowed_components)})
    scenes.append(recap)
    _decorate_components(scenes)
    return scenes, warnings


def topic(snapshots: list[dict[str, Any]]) -> str:
    return str(snapshots[0].get("topic") or "学习主题")


def default_title(snapshots: list[dict[str, Any]]) -> str:
    source = snapshots[0]
    return resource_courseware_title(str(source.get("title") or topic(snapshots)), snapshots)


def resource_courseware_title(title: str, snapshots: list[dict[str, Any]]) -> str:
    """Make the single-resource HTML version recognisable before its topic.

    A requester may supply an arbitrary course title, so the resource category
    cannot be left only in metadata or a small cover kicker.  It belongs in
    the largest title while avoiding a duplicate when a caller already wrote it.
    """
    label = str((snapshots[0] if snapshots else {}).get("resource_type") or "学习资源").strip()
    base = str(title or "互动课件").strip()
    return base if label and label in base else f"{label}｜{base}"


def source_summary(source: dict[str, Any], usage: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "resource_id": source["resource_id"], "resource_type": source["resource_type"],
        "resource_family_id": source.get("resource_family_id") or source["resource_id"],
        "version": source["version"], "content_hash": source["content_hash"], "role": source["role"],
        "batch_id": source.get("batch_id"), "topic": source.get("topic"),
        "knowledge_points": list(source.get("knowledge_points") or []),
        "has_verifiable_exercises": any(
            bool(item.get("question")) and item.get("answer") is not None
            for item in (source.get("exercise_items") or []) if isinstance(item, dict)
        ),
        "usage": dict(usage or {"adopted": True, "objective_ids": [], "scene_ids": []}),
    }
