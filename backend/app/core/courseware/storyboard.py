"""Source-bound storyboard branches and page grouping for learning design."""

from __future__ import annotations

import re
from collections.abc import Callable
from math import ceil
from typing import Any

from app.models.courseware.learning_design import (
    CoursewareLearningDesign, LearningObjectiveGraph, SourceConcept,
    SourceConceptIndex, StoryboardScene, StoryboardSpec,
)
from app.models.courseware.snapshots import LearnerContextSnapshot

_PRACTICE_STEP_MARKER = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:第\s*)?(?:步骤\s*)?(\d+|[一二三四五六七八九十]+)\s*(?:[、.．:：)）]|\s+-\s+|\s+)?\s*(.+)?$"
)

_PRACTICE_CONTEXT_TAIL = re.compile(r"^\s*#{1,6}\s*(?:总结|复盘|检查清单|练习|附录|常见问题)")

def _practice_step_groups(
    source: dict[str, Any], structured_steps: list[dict[str, Any]] | None = None,
) -> list[tuple[str, tuple[str, ...]]]:
    """Split a guide into source-bound, detailed step pages.

    A numbered/``步骤`` heading starts a page. Its following semantic source
    blocks stay with it so a page contains the operation detail, not merely a
    title. Unanchored text is context; it must never be fabricated as a step.
    """
    if structured_steps:
        return [
            (str(step["title"]).strip(), tuple(str(block_id) for block_id in step["source_block_ids"]))
            for step in structured_steps
        ]
    package = source.get("practice_guide_payload")
    if isinstance(package, dict) and package.get("schema_version") == "3.0":
        blocks_by_step = {
            str(block.get("practice_step_id")): str(block.get("block_id"))
            for block in source.get("blocks") or [] if block.get("practice_step_id") and block.get("block_id")
        }
        return [
            (str(step.get("title") or step.get("step_id") or "操作步骤"), (blocks_by_step[str(step["step_id"])],))
            for step in (package.get("practice") or {}).get("steps") or []
            if isinstance(step, dict) and str(step.get("step_id") or "") in blocks_by_step
        ]
    rows = [
        (str(block.get("block_id") or ""), str(block.get("text") or "").strip())
        for block in source.get("blocks") or []
        if str(block.get("block_id") or "") and str(block.get("text") or "").strip()
    ]
    groups: list[tuple[str, list[str]]] = []
    current_label = ""
    current_ids: list[str] = []
    ended = False
    for block_id, text in rows:
        if ended:
            continue
        block_kind = next((str(block.get("kind") or "") for block in source.get("blocks") or [] if str(block.get("block_id")) == block_id), "")
        if current_ids and block_kind == "heading" and _PRACTICE_CONTEXT_TAIL.match(text):
            groups.append((current_label, current_ids))
            current_label, current_ids, ended = "", [], True
            continue
        marker = _PRACTICE_STEP_MARKER.match(text) if block_kind in {"", "heading"} else None
        if marker:
            if current_ids:
                groups.append((current_label, current_ids))
            current_label = (marker.group(2) or text).strip()
            current_ids = [block_id]
        elif current_ids:
            current_ids.append(block_id)
        # Introductory, code and appendix blocks before an explicit step are
        # deliberately ignored by fallback page planning. They remain frozen
        # provenance, but are not operations.
    if current_ids:
        groups.append((current_label, current_ids))
    return [(label or f"完成操作 {index}", tuple(block_ids)) for index, (label, block_ids) in enumerate(groups, 1)]

def _practice_step_pages(source: dict[str, Any], block_ids: tuple[str, ...]) -> list[tuple[str, ...]]:
    """Keep one real step together, while allowing a dense step two pages.

    Splitting is only at frozen semantic-block boundaries; it never creates a
    new operation or changes the step ordering.  Two pages per step preserves
    detail without exceeding the 24-page release ceiling for a typical
    nine-step guide.
    """
    by_id = {str(block.get("block_id")): block for block in source.get("blocks") or []}
    total = sum(len(str(by_id.get(block_id, {}).get("text") or "")) for block_id in block_ids)
    if total <= 1500 or len(block_ids) < 3:
        return [block_ids]
    target = max(750, total // 2)
    first: list[str] = []
    used = 0
    for index, block_id in enumerate(block_ids):
        size = len(str(by_id.get(block_id, {}).get("text") or ""))
        # Keep the heading and enough explanation on the first page. Code is
        # already atomic in source snapshots and is never cut in half.
        if len(first) >= 2 and used + size > target:
            return [tuple(first), tuple(block_ids[index:])]
        first.append(block_id)
        used += size
    return [block_ids]


def build_review_design(
    review_checklist: dict[str, Any],
    *,
    add_scene: Callable[..., None],
    source_blocks: Callable[..., tuple[str, ...]],
    scenes: list[StoryboardScene],
    warnings: list[dict[str, str]],
    graph: LearningObjectiveGraph,
    context: LearnerContextSnapshot,
    snapshots: list[dict[str, Any]],
    usage_by_resource: dict[str, dict[str, Any]],
    bundle_hash: Callable[[list[dict[str, Any]]], str],
) -> CoursewareLearningDesign:
    """Build the existing review route without changing source bindings."""
    package = review_checklist["review_practice_payload"]
    question_blocks = {
        str(block.get("review_question_id")): str(block.get("block_id"))
        for block in review_checklist.get("blocks") or [] if block.get("review_question_id") and block.get("block_id")
    }
    summary_blocks = {
        str(block.get("skill_node_id")): str(block.get("block_id"))
        for block in review_checklist.get("blocks") or []
        if block.get("kind") == "review_summary" and block.get("skill_node_id") and block.get("block_id")
    }
    overview_blocks = tuple(question_blocks.values())[:1] or source_blocks(review_checklist, limit=1)

    def chunks(items: list[dict[str, Any]], size: int = 2) -> list[list[dict[str, Any]]]:
        return [items[start:start + size] for start in range(0, len(items), size)] or [[]]

    def example_questions(node: dict[str, Any]) -> list[dict[str, Any]]:
        questions = [item for item in (node.get("example_recognition_questions") or []) if isinstance(item, dict)]
        if questions:
            return questions
        legacy = node.get("example_recognition")
        return [legacy] if isinstance(legacy, dict) else []

    add_scene(scene_id="scene:review:overview", kind="intro", page_role="review_overview", recipe="review_overview",
              sources=[review_checklist], key_question="如何使用闭卷回忆、误区辨析与正反例判断完成复习？",
              purpose="review-orient", zones=("route", "node_map", "self_report"),
              components=("review_overview",), min_chars=80, max_chars=420, block_ids=overview_blocks)
    for index, node in enumerate(package.get("node_blocks") or [], 1):
        node_id = str(node.get("skill_node_id") or index)
        recall = [item for item in (node.get("recall_questions") or []) if isinstance(item, dict)]
        distinction = [item for item in (node.get("distinction_questions") or []) if isinstance(item, dict)]
        examples = example_questions(node)
        prefix = f"scene:review:node:{index}:{node_id}"
        for page_index, page_questions in enumerate(chunks(recall), 1):
            page_blocks = tuple(question_blocks.get(str(question.get("question_id"))) for question in page_questions
                                if question_blocks.get(str(question.get("question_id")))) or overview_blocks
            add_scene(scene_id=f"{prefix}:recall:{page_index}", kind="practice", page_role="review_recall", recipe="review_recall_grid",
                      sources=[review_checklist], key_question=f"闭卷回忆（第{page_index}页）：{node.get('skill_node_name') or node_id}", purpose="active-recall",
                      zones=("questions", "reveal", "self_report"), components=("review_recall_card",), min_chars=80, max_chars=900, block_ids=page_blocks)
        for page_index, page_questions in enumerate(chunks(distinction), 1):
            page_blocks = tuple(question_blocks.get(str(question.get("question_id"))) for question in page_questions
                                if question_blocks.get(str(question.get("question_id")))) or overview_blocks
            add_scene(scene_id=f"{prefix}:distinction:{page_index}", kind="practice", page_role="review_distinction", recipe="review_distinction_grid",
                      sources=[review_checklist], key_question=f"概念辨析（第{page_index}页）：{node.get('skill_node_name') or node_id}", purpose="misconception-calibration",
                      zones=("statements", "reveal", "self_report"), components=("review_distinction_card",), min_chars=80, max_chars=900, block_ids=page_blocks)
        example_blocks = tuple(question_blocks.get(str(question.get("question_id"))) for question in examples
                               if question_blocks.get(str(question.get("question_id")))) or overview_blocks
        add_scene(scene_id=f"{prefix}:example", kind="recap", page_role="review_example", recipe="review_example_focus",
                  sources=[review_checklist], key_question=f"正反例与边界：{node.get('skill_node_name') or node_id}", purpose="boundary-reflection",
                  zones=("candidates", "boundary", "node_summary"), components=(("review_example_card",) if examples else ("review_reflection",)), min_chars=80, max_chars=900, block_ids=example_blocks)
        summary = str(node.get("knowledge_summary") or "").strip()
        summary_block = summary_blocks.get(node_id)
        if summary and summary_block:
            add_scene(scene_id=f"{prefix}:summary", kind="recap", page_role="review_node_summary", recipe="review_node_summary",
                      sources=[review_checklist], key_question=f"知识小结：{node.get('skill_node_name') or node_id}", purpose="node-recap",
        zones=("core_concept", "boundary", "next_review"), components=("review_node_summary",), min_chars=100, max_chars=1400, block_ids=(summary_block,))
    add_scene(scene_id="scene:review:summary", kind="recap", page_role="summary_action", recipe="recap_dashboard",
              sources=[review_checklist], key_question="哪些节点已经完成自评，下一步应如何安排？", purpose="review-summary",
              zones=("completion", "self_report", "next_action"), components=("review_completion",), min_chars=80, max_chars=480, block_ids=overview_blocks)
    concept_rows = [{"concept_id": f"concept:{review_checklist['resource_id']}:{index}", "label": str(node.get("skill_node_name") or node.get("skill_node_id") or index), "source_refs": overview_blocks, "adopted_source_ids": (str(review_checklist["resource_id"]),)} for index, node in enumerate(package.get("node_blocks") or [])]
    for scene in scenes:
        usage_by_resource[str(review_checklist["resource_id"])]["scene_ids"].append(scene.scene_id)
    return CoursewareLearningDesign(schema_version="3.0", resource_bundle_hash=bundle_hash(snapshots), learner_context_hash=context.stable_hash(), objectives=graph,
        storyboard=StoryboardSpec(scenes=tuple(scenes), objective_graph_hash=graph.stable_hash()), resource_usage_plan=tuple(usage_by_resource.values()),
        source_concept_index=SourceConceptIndex(concepts=tuple(SourceConcept(**item) for item in concept_rows)),
        interaction_quota={"status": "review_practice_v3", "target_scenes": len(scenes), "target_interactions": sum(
            len(node.get("recall_questions") or []) + len(node.get("distinction_questions") or []) + len(example_questions(node))
            for node in (package.get("node_blocks") or [])
        )}, warnings=tuple(warnings))


def lecture_segments(source: dict[str, Any], *, max_groups: int, source_blocks: Callable[..., tuple[str, ...]]) -> list[tuple[str, ...]]:
    groups: list[list[str]] = []
    current: list[str] = []
    current_chars = 0
    for block in source.get("blocks") or []:
        block_id, size = str(block.get("block_id") or ""), len(str(block.get("text") or "").strip())
        if current and current_chars >= 240:
            groups.append(current)
            current, current_chars = [], 0
        if block_id:
            current.append(block_id)
            current_chars += size
    if current:
        groups.append(current)
    if len(groups) > 1:
        tail_chars = sum(
            len(str(block.get("text") or "").strip())
            for block in source.get("blocks") or [] if str(block.get("block_id")) in set(groups[-1])
        )
        if tail_chars < 160:
            groups[-2].extend(groups.pop())
    resolved = [tuple(group) for group in groups] or [source_blocks(source)]
    if len(resolved) <= max_groups:
        return resolved
    # Preserve source order and every source block, but merge adjacent
    # micro-stages into a richer, single-page teaching phase. This is a
    # planning repair, not a font-size or renderer workaround.
    merged: list[tuple[str, ...]] = []
    chunk_size = ceil(len(resolved) / max_groups)
    for offset in range(0, len(resolved), chunk_size):
        merged.append(tuple(block_id for group in resolved[offset:offset + chunk_size] for block_id in group))
    return merged


def append_practice_scenes(
    practices: list[dict[str, Any]],
    practice_step_structures: dict[str, list[dict[str, Any]]],
    *,
    add_scene: Callable[..., None],
    step_groups: Callable[..., list[tuple[str, tuple[str, ...]]]],
    step_pages: Callable[..., list[tuple[str, ...]]],
) -> None:
    """Append practice phases and step pages in their original source order."""
    for source in practices[:2]:
        phase_blocks = {
            str(block.get("practice_phase_id")): str(block.get("block_id"))
            for block in source.get("blocks") or [] if block.get("practice_phase_id") and block.get("block_id")
        }
        for phase_id, label in (("prepare", "准备阶段"),):
            block_id = phase_blocks.get(phase_id)
            if block_id:
                add_scene(
                    scene_id=f"scene:practice:{source['resource_id']}:phase:{phase_id}", kind="practice",
                    page_role="practice_workspace", recipe="practice_workspace", sources=[source],
                    key_question=f"{label}需要确认哪些前置条件？", purpose=f"practice-{phase_id}",
                    zones=("phase_goal", "phase_items", "completion_check"), components=("key_point", "steps"),
                    min_chars=120, max_chars=800, block_ids=(block_id,), practice_variant=phase_id,
                )
        step_groups = step_groups(source, practice_step_structures.get(str(source["resource_id"])))
        for step_index, (step_label, step_block_ids) in enumerate(step_groups, 1):
            page_groups = step_pages(source, step_block_ids)
            for part_index, page_block_ids in enumerate(page_groups, 1):
                # A practice page has a stable spatial contract: concise
                # completion control on the left and a large operation/code
                # workspace on the right.  Rotating it through generic
                # concept/process recipes made the title and code area move,
                # and those layouts can crop dense source-bound code.
                recipe = "practice_workspace"
                page_blocks = [
                    block for block in source.get("blocks") or []
                    if str(block.get("block_id")) in set(page_block_ids)
                ]
                # Code is a structural field of the V3 step JSON.  It must
                # select the matching fixed page layout instead of depending
                # on a rotating page index.
                has_code = any(block.get("code_blocks") for block in page_blocks)
                practice_variant = "code" if has_code else "guided"
                is_final_part = part_index == len(page_groups)
                part_suffix = "" if len(page_groups) == 1 else f"（说明 {part_index}/{len(page_groups)}）"
                scene_suffix = f":part:{part_index}" if len(page_groups) > 1 else ""
                add_scene(
                    scene_id=f"scene:practice:{source['resource_id']}:step:{step_index}{scene_suffix}", kind="practice",
                    page_role="practice_workspace", recipe=recipe, sources=[source],
                    key_question=f"步骤 {step_index}{part_suffix}：{step_label[:72]} 应如何完成并验收？",
                    purpose=f"apply-step-{step_index}-part-{part_index}",
                    zones=("step_goal", "operation_detail", "completion_check", "next_step"),
                    components=("key_point", "code_block", "callout"), min_chars=180, max_chars=1100,
                    block_ids=page_block_ids, practice_variant=practice_variant,
                )
        for phase_id, label in (("verify", "验证阶段"), ("reflect", "复盘阶段")):
            block_id = phase_blocks.get(phase_id)
            if block_id:
                add_scene(
                    scene_id=f"scene:practice:{source['resource_id']}:phase:{phase_id}", kind="practice",
                    page_role="practice_workspace", recipe="practice_workspace", sources=[source],
                    key_question=f"{label}需要如何完成？", purpose=f"practice-{phase_id}",
                    zones=("phase_goal", "phase_items", "completion_check"), components=("key_point", "callout") if phase_id == "reflect" else ("key_point", "steps"),
                    min_chars=120, max_chars=900, block_ids=(block_id,), practice_variant=phase_id,
                )
