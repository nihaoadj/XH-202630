"""Deterministic page-level quality gates for courseware 3.0 documents."""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

from app.core.courseware.design_system.recipes import SCENE_RECIPE_IDS


_CONCLUSION_OPTIONAL = {"cover", "learning_map"}


def _visible_text(scene: dict[str, Any]) -> str:
    values: list[Any] = [scene.get("lead"), *(scene.get("blocks") or []), *(scene.get("steps") or [])]
    values.extend([scene.get("feedback"), scene.get("conclusion")])
    # Review-practice V2 keeps its learner-visible prompts/answers in
    # renderer-owned item payloads rather than unsafe free-form prose blocks.
    # Count those fields for density without loosening ordinary page checks.
    for component in scene.get("component_blocks") or []:
        if not isinstance(component, dict) or not str(component.get("component") or "").startswith("review_"):
            continue
        values.append(component.get("text"))
        if component.get("component") == "review_completion":
            values.extend((component.get("overall_summary"), "节点完成情况", "自评结果"))
        items = component.get("items") or ([component.get("item")] if component.get("item") else [])
        for item in items:
            if isinstance(item, dict):
                values.extend(item.get(key) for key in ("prompt", "statement", "candidate_a", "candidate_b", "reference_answer", "correction", "explanation", "decisive_boundary"))
    return "".join(str(value).strip() for value in values if str(value or "").strip())


def page_quality_issues(document: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stable hard-gate codes; pixel overflow remains a browser verdict."""

    issues: list[dict[str, Any]] = []
    previous_signature: tuple[str, tuple[str, ...], str, tuple[str, ...]] | None = None
    for index, scene in enumerate(document.get("scenes") or []):
        role = str(scene.get("page_role") or "")
        if not role:  # Legacy 1.x/2.x documents remain playable without v3 gates.
            previous_signature = None
            continue
        scene_id = str(scene.get("scene_id") or f"scene-{index}")
        recipe = str(scene.get("layout_recipe_id") or scene.get("recipe_id") or "")
        text = _visible_text(scene)
        components = tuple(
            str(block.get("component") or "")
            for block in (scene.get("component_blocks") or []) if isinstance(block, dict)
        )
        effective_zones = len([block for block in (scene.get("component_blocks") or []) if isinstance(block, dict) and str(block.get("text") or "").strip()])
        # The completion component renders an overview and a node-status
        # section inside one registered component. Count those renderer-owned
        # regions separately so the designed summary page is not classified
        # as a thin page merely because it has one component block.
        if any(
            isinstance(block, dict)
            and block.get("component") == "review_completion"
            and (block.get("overall_summary") or block.get("items"))
            for block in scene.get("component_blocks") or []
        ):
            effective_zones += 2
        if role.startswith("review_"):
            for block in scene.get("component_blocks") or []:
                if isinstance(block, dict) and str(block.get("component") or "").startswith("review_"):
                    effective_zones += len(block.get("items") or []) or (1 if block.get("item") or block.get("reason") else 0)
        if scene.get("options"):
            effective_zones += 1
        if scene.get("feedback"):
            effective_zones += 1
        if scene.get("conclusion"):
            effective_zones += 1
        effective_zones = min(4, effective_zones)
        budget = scene.get("content_budget") or {}
        min_chars = int(budget.get("min_chars") or (80 if role == "cover" or role.startswith("review_") else 120 if role in {"learning_map", "knowledge_check", "summary_action"} else 220))
        min_zones = int(budget.get("min_zones") or (2 if role == "cover" or role.startswith("review_") else 3))

        def add(code: str, detail: str) -> None:
            issues.append({"code": code, "scene_id": scene_id, "scene_index": index, "detail": detail})

        if not text or (not effective_zones and not scene.get("options")):
            add("EMPTY_PAGE", "页面没有有效内容区")
        if len(text) < min_chars or effective_zones < min_zones:
            add("THIN_PAGE", f"内容 {len(text)} 字/信息区 {effective_zones}，低于预算 {min_chars}/{min_zones}")
        if recipe not in SCENE_RECIPE_IDS:
            add("UNPLANNED_LAYOUT", f"未注册页级 recipe: {recipe or '<empty>'}")
        if role not in _CONCLUSION_OPTIONAL and not str(scene.get("conclusion") or "").strip():
            add("MISSING_PAGE_CONCLUSION", "普通内容页缺少页面结论")
        if min_chars and len(text) < round(min_chars * .65):
            add("UNDERFILLED_PAGE", "主体信息量低于内容预算的 65%")
        signature = (role, components, text, tuple(str(value) for value in scene.get("source_block_ids") or []))
        if previous_signature:
            previous_role, previous_components, previous_text, previous_source_blocks = previous_signature
            similarity = SequenceMatcher(None, previous_text, text).ratio()
            # Many real guides deliberately use a repeated instructional
            # scaffold across distinct steps. Different frozen source blocks
            # prove those pages are not copied placeholders; only repeated
            # prose grounded in the same source range is a hard failure.
            if (role == previous_role and components == previous_components
                    and previous_source_blocks == signature[3] and similarity >= .78):
                add("REPETITIVE_PAGE", f"连续页面角色、组件与正文重复度过高（{similarity:.0%}）")
        previous_signature = signature
    return issues


__all__ = ["page_quality_issues"]
