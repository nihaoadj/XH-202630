"""Deterministic, source-bound learning design for interactive courseware.

The model may later enrich a scene, but this design is the platform-owned
outline.  It is deliberately built from frozen source metadata so learner
context can tune pacing without changing facts, answers, or provenance.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from app.models.courseware.learning_design import (
    CoursewareLearningDesign,
    LearningObjective,
    LearningObjectiveGraph,
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
        })
    encoded = json.dumps(sorted(payload, key=lambda item: item["resource_id"]), ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _difficulty(context: LearnerContextSnapshot) -> str:
    return {"beginner": "scaffolded", "基础": "scaffolded", "advanced": "challenge", "高级": "challenge"}.get(
        (context.level or "").strip().lower(), "neutral"
    )


def _density(context: LearnerContextSnapshot) -> str:
    return {"slow": "low", "慢": "low", "fast": "high", "快": "high"}.get(context.pace, "medium")


def build_learning_design(
    snapshots: list[dict[str, Any]],
    learner_context: LearnerContextSnapshot | dict[str, Any] | None = None,
    request_options: dict[str, Any] | None = None,
) -> CoursewareLearningDesign:
    """Build objective graph and storyboard before any learner-facing scene.

    Missing assessment/practice inputs are represented explicitly: no quiz is
    invented without an objective question/answer, and no practice steps are
    created when the practice snapshot has no content.
    """
    context = learner_context if isinstance(learner_context, LearnerContextSnapshot) else LearnerContextSnapshot(**(learner_context or {}))
    request_options = request_options or {}
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

    lecture = next((item for item in adopted_ordered if item.get("role") == "lecture" and item.get("content")), None)
    if lecture:
        rid = str(lecture["resource_id"])
        scenes.append(StoryboardScene(
            scene_id="scene:intro", kind="intro", objective_ids=(objective_by_resource[rid],),
            source_resource_ids=(rid,), source_block_ids=tuple(block["block_id"] for block in lecture.get("blocks", [])[:8]),
            difficulty=difficulty, information_density=density, interaction_purpose="orient",
            allowed_components=("callout", "key_point"), allowed_component_ids=("callout", "key_point"),
        ))
    scene_ordered = (
        [item for item in adopted_ordered if item.get("role") in {"lecture", "case_study"} and item is not lecture]
        + [item for item in adopted_ordered if item.get("role") == "practice"]
        + [item for item in adopted_ordered if item.get("role") == "assessment"]
    )
    for source in scene_ordered:
        role = source.get("role")
        rid = str(source["resource_id"])
        blocks = tuple(block["block_id"] for block in source.get("blocks", [])[:8] if block.get("block_id"))
        if role in {"lecture", "case_study"} and source.get("content") and source is not lecture:
            scenes.append(StoryboardScene(
                scene_id=f"scene:explain:{rid}", kind="explain", objective_ids=(objective_by_resource[rid],),
                source_resource_ids=(rid,), source_block_ids=blocks, difficulty=difficulty,
                information_density=density, interaction_purpose="explain",
                allowed_components=("callout", "key_point", "compare"), allowed_component_ids=("callout", "key_point", "compare"),
            ))
        elif role == "practice":
            if source.get("content"):
                scenes.append(StoryboardScene(
                    scene_id=f"scene:practice:{rid}", kind="practice", objective_ids=(objective_by_resource[rid],),
                    source_resource_ids=(rid,), source_block_ids=blocks, difficulty=difficulty,
                    information_density=density, interaction_purpose="apply", allowed_components=("steps", "ordered_steps"),
                    allowed_component_ids=("steps", "ordered_steps"),
                ))
        elif role == "assessment":
            usable = next((item for item in source.get("exercise_items") or []
                           if len(item.get("options") or []) >= 2 and item.get("answer") is not None), None)
            if usable:
                scenes.append(StoryboardScene(
                    scene_id=f"scene:quiz:{rid}", kind="quiz", objective_ids=(objective_by_resource[rid],),
                    source_resource_ids=(rid,), source_block_ids=blocks, difficulty=difficulty,
                    information_density=density, interaction_purpose="check", allowed_components=("single_choice", "multiple_choice"),
                    allowed_component_ids=("single_choice", "multiple_choice"),
                ))
    if not any(item.get("role") == "assessment" for item in adopted_ordered):
        warnings.append({"code": "ASSESSMENT_SCENE_OPTIONAL", "message": "未提供测试题资源，已省略自测场景；未生成答案"})
    if len(adopted_ordered) >= 2:
        first, second = adopted_ordered[0], adopted_ordered[1]
        relation_type = "conflict" if any(item.get("source_relation") == "conflict" for item in (first, second)) else "complementary"
        scenes.append(StoryboardScene(
            scene_id="scene:compare:cross-source", kind="compare", objective_ids=tuple(item.objective_id for item in objectives[:2]),
            source_resource_ids=(str(first["resource_id"]), str(second["resource_id"])),
            source_block_ids=tuple(str(block["block_id"]) for source in (first, second) for block in (source.get("blocks") or [])[:1] if block.get("block_id")),
            difficulty=difficulty, information_density=density, interaction_purpose="compare",
            allowed_components=("compare", "callout"), allowed_component_ids=("compare", "callout"),
        ))
    quota_table = {
        "low": {"5-15": (4, 1), "16-30": (6, 2), "31-60": (8, 3), "61-240": (10, 3)},
        "medium": {"5-15": (5, 2), "16-30": (7, 3), "31-60": (9, 4), "61-240": (11, 5)},
        "high": {"5-15": (5, 3), "16-30": (8, 4), "31-60": (10, 5), "61-240": (12, 6)},
    }
    band = "5-15" if duration <= 15 else "16-30" if duration <= 30 else "31-60" if duration <= 60 else "61-240"
    target_scenes, target_interactions = quota_table.get(intensity, quota_table["medium"])[band]
    verifiable = any(source.get("has_verifiable_exercises") or source.get("exercise_items") for source in adopted_ordered)
    quota_status = "met" if verifiable or intensity != "high" else "constrained"
    if quota_status == "constrained":
        warnings.append({"code": "INSUFFICIENT_SCORED_EVIDENCE", "message": "来源没有可验证练习，互动配额已受限"})
    while len(scenes) < min(target_scenes - 1, 12):
        source = adopted_ordered[len(scenes) % len(adopted_ordered)] if adopted_ordered else None
        if not source:
            break
        rid = str(source["resource_id"])
        block_ids = tuple(str(block["block_id"]) for block in (source.get("blocks") or [])[:1] if block.get("block_id"))
        scenes.append(StoryboardScene(
            scene_id=f"scene:example:{rid}:{len(scenes)}", kind="example", objective_ids=(f"objective:{rid}",),
            source_resource_ids=(rid,), source_block_ids=block_ids, difficulty=difficulty,
            information_density=density, interaction_purpose="example",
            allowed_components=("callout", "key_point", "flashcard"), allowed_component_ids=("callout", "key_point", "flashcard"),
        ))
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
