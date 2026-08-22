"""Deterministic scene composition for the courseware service."""

from typing import Any

from app.agents.resource_workflows.interactive_courseware.contracts import CoursewareSpec


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
                "source_refs": [source["resource_id"]], "source_block_ids": source_block_ids,
                "source_map": {"blocks": [source_block_ids],
                               "options": [source_block_ids for _ in options], "answer": [source_block_ids]},
            }
    return None


def compose_scenes(
    snapshots: list[dict[str, Any]], plan: CoursewareSpec | None = None
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    scenes: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    by_id = {item["resource_id"]: item for item in snapshots}
    ordered_sources = [by_id[item.source_resource_id] for item in plan.scenes if item.source_resource_id in by_id] if plan else snapshots
    for source in ordered_sources:
        try:
            if source["role"] in {"lecture", "case_study"} and source["content"]:
                kind = "intro" if not scenes else "explain"
                source_block_ids = [item["block_id"] for item in source.get("blocks", [])[:8]]
                scenes.append({
                    "kind": kind, "title": "学习目标" if kind == "intro" else source["resource_type"],
                    "blocks": _paragraphs(source["content"]), "source_refs": [source["resource_id"]],
                    "source_block_ids": source_block_ids,
                    "source_map": {"blocks": [[block_id] for block_id in source_block_ids]},
                })
            elif source["role"] == "practice" and source["content"]:
                steps = _steps(source["content"])
                source_block_ids = [item["block_id"] for item in source.get("blocks", [])[:8]]
                scenes.append({
                    "kind": "practice", "title": "动手练习",
                    "blocks": ["请按步骤完成练习，并勾选已完成项。"], "steps": steps,
                    "source_refs": [source["resource_id"]], "source_block_ids": source_block_ids,
                    "source_map": {"blocks": [source_block_ids],
                                   "steps": [[block_id] for block_id in source_block_ids[:len(steps)]]},
                })
            elif source["role"] == "assessment":
                quiz = _quiz(source)
                if quiz:
                    scenes.append(quiz)
                else:
                    warnings.append({"code": "ASSESSMENT_SCENE_SKIPPED", "message": "测试题缺少可安全映射的客观题，已跳过自测场景"})
        except Exception:
            warnings.append({"code": "SCENE_SKIPPED", "message": f"{source['resource_type']} 场景生成失败，其他场景继续发布"})
    points = [point for item in snapshots for point in item.get("knowledge_points", [])][:8]
    recap_block_ids = [block["block_id"] for item in snapshots for block in item.get("blocks", [])[:1]]
    scenes.append({
        "kind": "recap", "title": "复盘",
        "blocks": ["本课件已完成。请回顾以下知识点：", "、".join(points) or "请回顾本节的核心内容。"],
        "source_refs": [item["resource_id"] for item in snapshots],
        "source_block_ids": recap_block_ids,
        "source_map": {"blocks": [recap_block_ids, recap_block_ids]},
    })
    return scenes, warnings


def topic(snapshots: list[dict[str, Any]]) -> str:
    return str(snapshots[0].get("topic") or "学习主题")


def default_title(snapshots: list[dict[str, Any]]) -> str:
    return f"{topic(snapshots)}互动课件"


def source_summary(source: dict[str, Any]) -> dict[str, Any]:
    return {
        "resource_id": source["resource_id"], "resource_type": source["resource_type"],
        "resource_family_id": source.get("resource_family_id") or source["resource_id"],
        "version": source["version"], "content_hash": source["content_hash"], "role": source["role"],
    }
