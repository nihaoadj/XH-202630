"""Deterministic scene composition for the courseware service."""

from typing import Any

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSpec
from app.models.courseware.learning_design import CoursewareLearningDesign


def _paragraphs(content: str) -> list[str]:
    parts = [part.strip(" #-\t") for part in content.split("\n") if part.strip()]
    return parts[:8] or ["源资源内容为空。"]


def _steps(content: str) -> list[str]:
    values = [part.strip(" #-*0123456789.、\t") for part in content.split("\n") if part.strip()]
    return [item for item in values if item][:8] or ["阅读实操指南并完成关键步骤。"]


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


def compose_scenes(
    snapshots: list[dict[str, Any]], plan: CoursewareSpec | None = None,
    *, learning_design: CoursewareLearningDesign | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
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
    return f"{topic(snapshots)}互动课件"


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
