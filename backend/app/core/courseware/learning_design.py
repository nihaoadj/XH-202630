"""Deterministic, source-bound learning design for interactive courseware.

The model may later enrich a scene, but this design is the platform-owned
outline.  It is deliberately built from frozen source metadata so learner
context can tune pacing without changing facts, answers, or provenance.
"""

from __future__ import annotations

import hashlib
import json
import re
from math import ceil
from typing import Any

from app.models.courseware.learning_design import (
    CoursewareLearningDesign,
    LearningObjective,
    LearningObjectiveGraph,
    SourceConcept,
    SourceConceptIndex,
    StoryboardScene,
    StoryboardSpec,
)
from app.models.courseware.snapshots import LearnerContextSnapshot, ResourceBundleSnapshot


def _bundle_hash(snapshots: list[dict[str, Any]]) -> str:
    """Hash only immutable source identity and block identity, never ordering prose."""
    payload = []
    for raw in snapshots:
        frozen = ResourceBundleSnapshot.from_snapshot(raw)
        payload.append({
            "resource_id": frozen.resource_id,
            "resource_type": frozen.resource_type,
            "role": frozen.role,
            "version": frozen.version,
            "content_hash": frozen.content_hash,
            "batch_id": frozen.batch_id,
            "topic": frozen.topic,
            "knowledge_points": list(frozen.knowledge_points),
            "has_verifiable_exercises": frozen.has_verifiable_exercises,
            "source_block_ids": list(frozen.source_block_ids),
            "review_practice_payload_hash": raw.get("review_practice_payload_hash"),
            "practice_guide_payload_hash": raw.get("practice_guide_payload_hash"),
        })
    encoded = json.dumps(sorted(payload, key=lambda item: item["resource_id"]), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _difficulty(context: LearnerContextSnapshot) -> str:
    return {"beginner": "scaffolded", "基础": "scaffolded", "advanced": "challenge", "高级": "challenge"}.get(
        (context.level or "").strip().lower(), "neutral"
    )


def _density(context: LearnerContextSnapshot) -> str:
    return {"slow": "low", "慢": "low", "fast": "high", "快": "high"}.get(context.pace, "medium")


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


def build_learning_design(
    snapshots: list[dict[str, Any]],
    learner_context: LearnerContextSnapshot | dict[str, Any] | None = None,
    request_options: dict[str, Any] | None = None,
    practice_step_structures: dict[str, list[dict[str, Any]]] | None = None,
) -> CoursewareLearningDesign:
    """Build objective graph and storyboard before any learner-facing scene.

    Missing assessment/practice inputs are represented explicitly: no quiz is
    invented without an objective question/answer, and no practice steps are
    created when the practice snapshot has no content.
    """
    context = learner_context if isinstance(learner_context, LearnerContextSnapshot) else LearnerContextSnapshot(**(learner_context or {}))
    request_options = request_options or {}
    practice_step_structures = practice_step_structures or {}
    duration = int(request_options.get("expected_duration_minutes") or 15)
    intensity = str(request_options.get("interaction_intensity") or "medium")
    ordered = sorted(snapshots, key=lambda item: str(item.get("resource_id", "")))
    usage_by_resource: dict[str, dict[str, Any]] = {}
    seen_source_identity: dict[tuple[str, str], str] = {}
    for source in ordered:
        resource_id = str(source["resource_id"])
        identity = (str(source.get("resource_family_id") or resource_id), str(source.get("content_hash") or ""))
        duplicate_of = seen_source_identity.get(identity)
        reason = None
        if duplicate_of:
            reason = "duplicate_source"
        elif source.get("role") == "assessment" and not any(
            len(item.get("options") or []) >= 2 and item.get("answer") is not None
            for item in source.get("exercise_items") or [] if isinstance(item, dict)
        ):
            reason = "missing_verifiable_exercise"
        elif source.get("role") in {"lecture", "case_study", "practice"} and not source.get("content"):
            reason = "empty_source"
        usage_by_resource[resource_id] = {
            "resource_id": resource_id, "adopted": reason is None,
            "objective_ids": [], "scene_ids": [], "unused_reason": reason,
            "relation": "duplicate" if duplicate_of else "complementary",
            "duplicate_of": duplicate_of,
        }
        if not duplicate_of:
            seen_source_identity[identity] = resource_id
    adopted_ordered = []
    for item in ordered:
        if usage_by_resource[str(item["resource_id"])].get("adopted"):
            adopted_ordered.append(item)
    objectives: list[LearningObjective] = []
    previous: str | None = None
    for source in adopted_ordered:
        resource_id = str(source["resource_id"])
        objective_id = f"objective:{resource_id}"
        concepts = tuple(str(item) for item in (source.get("knowledge_points") or []) if str(item).strip())[:8]
        role = str(source.get("role") or "lecture")
        statement = {
            "practice": "能够依据冻结来源完成关键实践步骤。",
            "assessment": "能够使用冻结来源中的标准答案完成自测。",
            "case_study": "能够解释案例中的关键判断与依据。",
        }.get(role, "能够概括并解释本资源的核心概念。")
        objectives.append(LearningObjective(
            objective_id=objective_id,
            statement=statement,
            prerequisite_ids=(previous,) if previous else (),
            core_concepts=concepts,
            common_mistakes=(),
            observable_result="能用自己的话说明依据，并完成对应交互。",
            source_resource_ids=(resource_id,),
            source_block_ids=tuple(str(block.get("block_id")) for block in (source.get("blocks") or []) if block.get("block_id")),
        ))
        previous = objective_id
    graph = LearningObjectiveGraph(objectives=tuple(objectives))
    difficulty = _difficulty(context)
    density = _density(context)
    scenes: list[StoryboardScene] = []
    warnings: list[dict[str, str]] = []
    objective_by_resource = {rid: f"objective:{rid}" for rid in (str(item["resource_id"]) for item in adopted_ordered)}

    def source_blocks(*sources: dict[str, Any], limit: int = 8) -> tuple[str, ...]:
        return tuple(
            str(block["block_id"])
            for source in sources for block in (source.get("blocks") or [])
            if block.get("block_id")
        )[:limit]

    def add_scene(
        *, scene_id: str, kind: str, page_role: str, recipe: str,
        sources: list[dict[str, Any]], key_question: str, purpose: str,
        zones: tuple[str, ...], components: tuple[str, ...],
        min_chars: int = 220, max_chars: int = 650,
        block_ids: tuple[str, ...] | None = None,
        practice_variant: str | None = None,
    ) -> None:
        resource_ids = tuple(str(source["resource_id"]) for source in sources)
        scenes.append(StoryboardScene(
            scene_id=scene_id, kind=kind, page_role=page_role, layout_recipe_id=recipe,
            key_question=key_question, required_zones=zones,
            content_budget={"min_zones": len(zones), "max_zones": 4, "min_chars": min_chars, "max_chars": max_chars},
            objective_ids=tuple(objective_by_resource[rid] for rid in resource_ids if rid in objective_by_resource),
            source_resource_ids=resource_ids, source_block_ids=block_ids or source_blocks(*sources),
            difficulty=difficulty, information_density=density, interaction_purpose=purpose,
            allowed_components=components, allowed_component_ids=components,
            practice_variant=practice_variant,
        ))

    lectures = [item for item in adopted_ordered if item.get("role") == "lecture" and item.get("content")]
    lecture = lectures[0] if lectures else None
    cases = [item for item in adopted_ordered if item.get("role") == "case_study" and item.get("content")]
    practices = [item for item in adopted_ordered if item.get("role") == "practice" and item.get("content")]
    assessments = [item for item in adopted_ordered if item.get("role") == "assessment"]
    checklists = [item for item in adopted_ordered if item.get("role") == "checklist" and item.get("content")]
    review_checklist = next((item for item in checklists if isinstance(item.get("review_practice_payload"), dict)
                             and item["review_practice_payload"].get("schema_version") == "2.0"), None)
    usable_assessment = next((source for source in assessments if any(
        len(item.get("options") or []) >= 2 and item.get("answer") is not None
        for item in source.get("exercise_items") or [] if isinstance(item, dict)
    )), None)
    band = "5-15" if duration <= 15 else "16-30" if duration <= 30 else "31-60" if duration <= 60 else "61-240"
    if review_checklist:
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
        return CoursewareLearningDesign(schema_version="3.0", resource_bundle_hash=_bundle_hash(snapshots), learner_context_hash=context.stable_hash(), objectives=graph,
            storyboard=StoryboardSpec(scenes=tuple(scenes), objective_graph_hash=graph.stable_hash()), resource_usage_plan=tuple(usage_by_resource.values()),
            source_concept_index=SourceConceptIndex(concepts=tuple(SourceConcept(**item) for item in concept_rows)),
            interaction_quota={"status": "review_practice_v3", "target_scenes": len(scenes), "target_interactions": sum(
                len(node.get("recall_questions") or []) + len(node.get("distinction_questions") or []) + len(example_questions(node))
                for node in (package.get("node_blocks") or [])
            )}, warnings=tuple(warnings))
    # Practice guides use one complete page per source step.  The cap protects
    # free-form lecture segmentation only; it must never merge guide steps.
    scene_cap = {"5-15": 10, "16-30": 14, "31-60": 20, "61-240": 24}[band]
    anchor = lecture or (cases[0] if cases else (adopted_ordered[0] if adopted_ordered else None))
    if anchor:
        add_scene(
            scene_id="scene:intro", kind="intro", page_role="cover", recipe="editorial_cover",
            sources=[anchor], key_question="这门课程能帮助我解决什么问题？", purpose="orient",
            zones=("course_value", "knowledge_scope", "duration_route"), components=("callout", "key_point"),
            min_chars=80, max_chars=360,
        )
    if len(adopted_ordered) >= 2:
        add_scene(
            scene_id="scene:learning-map", kind="explain", page_role="learning_map", recipe="learning_map_grid",
            sources=adopted_ordered[:4], key_question="本课程的知识与实践路径如何衔接？", purpose="navigate",
            zones=("objective_map", "chapter_path", "completion_route"), components=("key_point", "steps"),
            min_chars=120, max_chars=420,
        )
    non_lecture_scene_count = (
        int(bool(anchor)) + int(len(adopted_ordered) >= 2) + len(cases[:2])
        + int(len(adopted_ordered) >= 2) + sum(3 +
            sum(len(_practice_step_pages(item, block_ids)) for _, block_ids in _practice_step_groups(
                item, practice_step_structures.get(str(item["resource_id"]))
            ))
            for item in practices[:2]
        ) + len(checklists[:1])
        + int(bool(usable_assessment)) + 1  # recap
    )
    lecture_page_budget = max(1, scene_cap - non_lecture_scene_count) if lectures else 0

    def lecture_segments(source: dict[str, Any], *, max_groups: int) -> list[tuple[str, ...]]:
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

    remaining_lecture_budget = lecture_page_budget
    for lecture_index, lecture_source in enumerate(lectures):
        remaining_sources = len(lectures) - lecture_index
        source_budget = max(1, remaining_lecture_budget - (remaining_sources - 1))
        raw_segment_count = len(lecture_segments(lecture_source, max_groups=10_000))
        segments = lecture_segments(lecture_source, max_groups=source_budget)
        remaining_lecture_budget -= len(segments)
        if len(segments) < raw_segment_count:
            warnings.append({
                "code": "COURSEWARE_SCENE_CAP_APPLIED",
                "message": f"讲义分阶段内容已合并为 {len(segments)} 页，以满足桌面课件可发布页数上限",
            })
        for phase_index, segment in enumerate(segments, 1):
            component_order = ("key_point", "callout", "compare") if phase_index % 2 else ("callout", "compare", "key_point")
            add_scene(
                scene_id=f"scene:lecture:{lecture_source['resource_id']}:{phase_index}", kind="explain",
                page_role="concept_explanation", recipe="concept_split", sources=[lecture_source],
                key_question=f"讲义第 {phase_index} 阶段需要掌握什么，并如何衔接下一阶段？",
                purpose=f"learn-stage-{phase_index}", zones=("lead", "concepts", "evidence", "conclusion"),
                components=component_order, block_ids=segment,
            )
    for source in cases[:2]:
        add_scene(
            scene_id=f"scene:case:{source['resource_id']}", kind="scenario", page_role="case_diagnosis", recipe="case_diagnostic",
            sources=[source], key_question="案例中的问题如何定位，结论由哪些证据支持？", purpose="diagnose",
            zones=("background", "problem", "diagnosis", "conclusion"), components=("callout", "compare", "key_point"),
        )
    if len(adopted_ordered) >= 2:
        first, second = adopted_ordered[0], adopted_ordered[1]
        add_scene(
            scene_id="scene:compare:cross-source", kind="compare", page_role="comparison_analysis", recipe="comparison_matrix",
            sources=[first, second], key_question="这些方案在哪些条件下相同，又应如何取舍？", purpose="compare",
            zones=("criteria", "comparison", "evidence", "conclusion"), components=("compare", "key_point", "callout"),
        )
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
        step_groups = _practice_step_groups(source, practice_step_structures.get(str(source["resource_id"])))
        for step_index, (step_label, step_block_ids) in enumerate(step_groups, 1):
            page_groups = _practice_step_pages(source, step_block_ids)
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
    for source in checklists[:1]:
        add_scene(
            scene_id=f"scene:checklist:{source['resource_id']}", kind="practice", page_role="practice_workspace", recipe="practice_workspace",
            sources=[source], key_question="如何使用复习清单逐项确认掌握状态？", purpose="verify",
            zones=("review_goal", "check_items", "evidence", "completion_criteria"),
            components=("key_point", "steps", "callout"), min_chars=120, max_chars=480,
        )
    if usable_assessment:
        add_scene(
            scene_id=f"scene:quiz:{usable_assessment['resource_id']}", kind="quiz", page_role="knowledge_check", recipe="quiz_focus",
            sources=[usable_assessment], key_question="我能否识别正确判断，并解释错误选项的问题？", purpose="check",
            zones=("question", "answer", "feedback", "next_action"), components=("single_choice", "multiple_choice", "callout"),
            min_chars=60, max_chars=480,
        )
    elif assessments:
        # Only an assessment resource is expected to supply answer-backed
        # questions.  A resource-scoped guide, lecture, case, or checklist
        # must not be degraded merely because it is not also a test bank.
        warnings.append({"code": "ASSESSMENT_SCENE_OPTIONAL", "message": "测试题资源缺少可验证题目，已省略答题页；未生成答案"})
    quota_table = {
        "low": {"5-15": (5, 1), "16-30": (8, 2), "31-60": (11, 3), "61-240": (14, 3)},
        "medium": {"5-15": (7, 2), "16-30": (11, 3), "31-60": (14, 4), "61-240": (16, 5)},
        "high": {"5-15": (8, 3), "16-30": (12, 4), "31-60": (15, 5), "61-240": (16, 6)},
    }
    target_scenes, target_interactions = quota_table.get(intensity, quota_table["medium"])[band]
    verifiable = any(source.get("has_verifiable_exercises") or source.get("exercise_items") for source in adopted_ordered)
    quota_status = "met" if verifiable or intensity != "high" else "constrained"
    if quota_status == "constrained":
        warnings.append({"code": "INSUFFICIENT_SCORED_EVIDENCE", "message": "来源没有可验证练习，互动配额已受限"})
    if len(scenes) + 1 < target_scenes:
        warnings.append({
            "code": "SOURCE_DENSITY_REDUCED_PAGE_COUNT",
            "message": f"冻结来源仅支持 {len(scenes) + 1} 个完整页面，已减少页数而非循环复制内容",
        })
    concept_rows = []
    for source in adopted_ordered:
        rid = str(source["resource_id"])
        for index, label in enumerate(source.get("knowledge_points") or [source.get("topic") or rid]):
            concept_rows.append({"concept_id": f"concept:{rid}:{index}", "label": str(label), "source_refs": tuple(str(block.get("block_id")) for block in (source.get("blocks") or [])[:2] if block.get("block_id")), "adopted_source_ids": (rid,)})
    relations = []
    for index in range(1, len(adopted_ordered)):
        left = str(adopted_ordered[index - 1]["resource_id"])
        right = str(adopted_ordered[index]["resource_id"])
        relation_type = "conflict" if any(item.get("source_relation") == "conflict" for item in (adopted_ordered[index - 1], adopted_ordered[index])) else "complementary"
        relations.append({"relation_type": relation_type, "from_concept_id": f"concept:{left}:0", "to_concept_id": f"concept:{right}:0", "source_refs": ()})
    recap_sources = tuple(str(item["resource_id"]) for item in adopted_ordered)
    recap_blocks = tuple(str(block["block_id"]) for item in adopted_ordered for block in (item.get("blocks") or [])[:1] if block.get("block_id"))
    scenes.append(StoryboardScene(
        scene_id="scene:recap", kind="recap", objective_ids=tuple(item.objective_id for item in objectives),
        source_resource_ids=recap_sources, source_block_ids=recap_blocks, difficulty=difficulty,
        information_density=density, interaction_purpose="recall",
        allowed_components=("recap",), allowed_component_ids=("recap",),
        page_role="summary_action", layout_recipe_id="recap_dashboard",
        key_question="我已经完成了哪些目标，下一步应采取什么行动？",
        required_zones=("objective_status", "core_conclusions", "next_actions"),
        content_budget={"min_zones": 3, "max_zones": 4, "min_chars": 120, "max_chars": 420},
    ))
    for scene in scenes:
        for resource_id in scene.source_resource_ids:
            if resource_id in usage_by_resource and scene.scene_id not in usage_by_resource[resource_id]["scene_ids"]:
                usage_by_resource[resource_id]["scene_ids"].append(scene.scene_id)
    for resource_id, usage in usage_by_resource.items():
        if usage["adopted"]:
            usage["objective_ids"] = [f"objective:{resource_id}"]
    storyboard = StoryboardSpec(scenes=tuple(scenes), objective_graph_hash=graph.stable_hash())
    return CoursewareLearningDesign(
        resource_bundle_hash=_bundle_hash(snapshots), learner_context_hash=context.stable_hash(),
        objectives=graph, storyboard=storyboard,
        resource_usage_plan=tuple(usage_by_resource[str(item["resource_id"])] for item in ordered),
        source_concept_index={"concepts": concept_rows, "relations": relations},
        interaction_quota={"status": quota_status, "target": target_interactions, "actual": min(target_interactions, len(scenes)), "target_scene_count": target_scenes, "actual_scene_count": len(scenes), "reason": "INSUFFICIENT_SCORED_EVIDENCE" if quota_status == "constrained" else None},
        warnings=tuple(warnings),
    )


__all__ = ["build_learning_design"]
