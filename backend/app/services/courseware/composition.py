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
        structured_practice_source = sources[0] if len(sources) == 1 and sources[0].get("role") == "practice" else None
        practice_package = structured_practice_source.get("practice_guide_payload") if structured_practice_source else None
        practice_step_id = next(
            (str(block.get("practice_step_id")) for _, block in selected_blocks if block.get("practice_step_id")),
            None,
        )
        practice_phase_id = next(
            (str(block.get("practice_phase_id")) for _, block in selected_blocks if block.get("practice_phase_id")),
            None,
        )
        if (slot.kind == "practice" and isinstance(practice_package, dict)
                and practice_package.get("schema_version") == "3.0" and (practice_step_id or practice_phase_id)):
            source_id = str(structured_practice_source["resource_id"])
            source_refs = [{"source_resource_id": source_id, "source_block_ids": block_ids}]
            if practice_phase_id in {"prepare", "verify", "reflect"}:
                phase_key = {"prepare": "preparation", "verify": "verification", "reflect": "reflection"}[practice_phase_id]
                phase = practice_package[phase_key]
                items = list(phase.get("items") or phase.get("checklist") or [])
                labels = {"prepare": "准备阶段", "verify": "验证阶段", "reflect": "复盘与小结"}
                item_path = {"prepare": "preparation.items", "verify": "verification.checklist"}.get(practice_phase_id)
                evidence_path = f"{phase_key}.evidence_ids"
                display_blocks = [str(item) for item in items]
                component_blocks = [
                    {
                        "schema_version": "1.0", "block_id": f"{slot.scene_id}:goal", "component": "key_point",
                        "label": {"prepare": "阶段目标", "verify": "验证目标", "reflect": "复盘目标"}.get(practice_phase_id, "阶段目标"),
                        "presentation_role": (
                            "practice_phase_goal" if practice_phase_id == "prepare"
                            else "practice_phase_completion" if practice_phase_id == "verify"
                            else "practice_reflection_goal"
                        ),
                        "text": str(phase.get("goal") or ""), "source_json_path": f"{phase_key}.goal",
                        "evidence_json_path": evidence_path, "source_refs": source_refs,
                    },
                ]
                if item_path:
                    component_blocks.append({
                        "schema_version": "1.0", "block_id": f"{slot.scene_id}:items", "component": "steps",
                        "text": "准备项目" if practice_phase_id == "prepare" else "最终检查项",
                        "presentation_role": "practice_phase_items", "steps": display_blocks,
                        "source_json_path": item_path, "evidence_json_path": evidence_path, "source_refs": source_refs,
                    })
                if practice_phase_id == "reflect":
                    summary = str(phase.get("summary") or "")
                    display_blocks = [summary]
                    component_blocks.append({"schema_version": "1.0", "block_id": f"{slot.scene_id}:summary", "component": "callout", "label": "复盘小结", "presentation_role": "practice_reflection_summary", "text": summary, "source_json_path": "reflection.summary", "evidence_json_path": evidence_path, "source_refs": source_refs})
                scene = {
                    "scene_id": slot.scene_id, "kind": "practice", "page_role": "practice_workspace",
                    "layout_recipe_id": slot.layout_recipe_id or "practice_workspace", "key_question": slot.key_question,
                    "practice_variant": practice_phase_id, "practice_json_schema_version": "3.0", "practice_json_subject": phase_key, "required_zones": list(slot.required_zones),
                    "content_budget": slot.content_budget.model_dump(mode="json"), "title": labels[practice_phase_id],
                    "lead": str(phase.get("goal") or ""), "blocks": display_blocks,
                    "conclusion": f"完成{labels[practice_phase_id]}后，再进入下一阶段。", "steps": [str(item) for item in items],
                    "source_refs": [source_id], "source_block_ids": block_ids,
                    "objective_ids": list(slot.objective_ids), "allowed_component_ids": list(slot.allowed_component_ids),
                    "source_map": {"title": [block_ids], "lead": [block_ids], "blocks": [block_ids], "conclusion": [block_ids], "steps": [block_ids]},
                    "component_blocks": component_blocks,
                }
                scenes.append(scene)
                continue
            practice_step = next(
                (step for step in (practice_package.get("practice") or {}).get("steps") or []
                 if isinstance(step, dict) and str(step.get("step_id")) == practice_step_id),
                None,
            )
            if practice_step is None:
                warnings.append({"code": "PRACTICE_JSON_STEP_MISSING", "message": f"{slot.scene_id} 缺少对应 JSON 步骤"})
                continue
            step_number = practice_step_id.removeprefix("step-")
            verification = str(practice_step.get("verification") or "").strip()
            instruction = str(practice_step.get("instruction_text") or "").strip()
            code_blocks = [block for block in practice_step.get("code_blocks") or [] if isinstance(block, dict)]
            scene = {
                "scene_id": slot.scene_id, "kind": "practice", "page_role": "practice_workspace",
                "layout_recipe_id": slot.layout_recipe_id or "practice_workspace",
                "key_question": slot.key_question, "practice_variant": slot.practice_variant, "practice_json_schema_version": "3.0", "practice_json_subject": f"practice.steps.{practice_step_id}", "title_source_json_path": f"practice.steps.{practice_step_id}.title",
                "required_zones": list(slot.required_zones), "content_budget": slot.content_budget.model_dump(mode="json"),
                "title": f"步骤 {step_number}｜{str(practice_step.get('title') or practice_step_id)}",
                "lead": instruction, "blocks": [instruction, f"完成验证：{verification}"],
                "conclusion": f"完成本步骤的验证：{verification}", "steps": [],
                "source_refs": [source_id], "source_block_ids": block_ids,
                "objective_ids": list(slot.objective_ids), "allowed_component_ids": list(slot.allowed_component_ids),
                "source_map": {
                    "title": [block_ids],
                    "lead": [block_ids],
                    "blocks": [block_ids, block_ids, block_ids],
                    "conclusion": [block_ids],
                    "steps": [block_ids],
                },
                "component_blocks": [
                    {"schema_version": "1.0", "block_id": f"{slot.scene_id}:instruction", "component": "key_point", "text": instruction, "source_json_path": f"practice.steps.{practice_step_id}.instruction_text", "evidence_json_path": f"practice.steps.{practice_step_id}.evidence_ids", "source_refs": source_refs},
                    *[{"schema_version": "1.0", "block_id": f"{slot.scene_id}:code:{index}", "component": "code_block", "text": str(code_block.get("purpose") or "代码"), "language": str(code_block.get("language") or "text"), "code": str(code_block.get("code") or ""), "purpose": str(code_block.get("purpose") or ""), "source_json_path": f"practice.steps.{practice_step_id}.code_blocks.{index - 1}", "evidence_json_path": f"practice.steps.{practice_step_id}.code_blocks.{index - 1}.evidence_ids", "source_refs": source_refs} for index, code_block in enumerate(code_blocks, 1)],
                    {"schema_version": "1.0", "block_id": f"{slot.scene_id}:verification", "component": "callout", "label": "完成验证", "text": verification, "presentation_role": "practice_verification", "source_json_path": f"practice.steps.{practice_step_id}.verification", "evidence_json_path": f"practice.steps.{practice_step_id}.evidence_ids", "source_refs": source_refs},
                ],
            }
            scenes.append(scene)
            continue
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
                f"学习概述：{source_content_parts[0]}",
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


def _review_practice_scenes(snapshots: list[dict[str, Any]], enrichment: Any | None = None) -> list[dict[str, Any]] | None:
    """Project an audited review package into fixed, renderer-owned pages."""
    source = next((item for item in snapshots if item.get("role") == "checklist" and isinstance(item.get("review_practice_payload"), dict)
                   and item["review_practice_payload"].get("schema_version") == "2.0"), None)
    if source is None:
        return None
    package = source["review_practice_payload"]
    enrichment_data = enrichment.model_dump(mode="json") if hasattr(enrichment, "model_dump") else (enrichment if isinstance(enrichment, dict) else {})
    summaries = {str(item.get("skill_node_id")): str(item.get("summary")) for item in enrichment_data.get("node_summaries") or [] if isinstance(item, dict)}
    block_by_question = {str(block.get("review_question_id")): str(block.get("block_id")) for block in source.get("blocks") or [] if block.get("review_question_id")}
    block_by_summary = {str(block.get("skill_node_id")): str(block.get("block_id")) for block in source.get("blocks") or [] if block.get("kind") == "review_summary" and block.get("skill_node_id")}
    resource_id = str(source["resource_id"])
    def refs(ids: list[str]) -> list[dict[str, Any]]:
        return [{"source_resource_id": resource_id, "source_block_ids": ids or [next(iter(block_by_question.values()), "review-source")]}]
    def question_ids(node: dict[str, Any]) -> list[str]:
        examples = [item for item in (node.get("example_recognition_questions") or []) if isinstance(item, dict)]
        if not examples and isinstance(node.get("example_recognition"), dict):
            examples = [node["example_recognition"]]
        return [str(item.get("question_id")) for item in [*(node.get("recall_questions") or []), *(node.get("distinction_questions") or []), *examples] if isinstance(item, dict) and item.get("question_id")]
    def chunks(items: list[dict[str, Any]], size: int = 2) -> list[list[dict[str, Any]]]:
        return [items[start:start + size] for start in range(0, len(items), size)] or [[]]
    def example_questions(node: dict[str, Any]) -> list[dict[str, Any]]:
        questions = [item for item in (node.get("example_recognition_questions") or []) if isinstance(item, dict)]
        if questions:
            return questions
        legacy = node.get("example_recognition")
        return [legacy] if isinstance(legacy, dict) else []
    scenes: list[dict[str, Any]] = []
    nodes = package.get("node_blocks") or []
    overview_ids = [block_by_question[item] for node in nodes for item in question_ids(node) if item in block_by_question][:1]
    node_items = [{"label": str(node.get("skill_node_name") or node.get("skill_node_id")), "value": "闭卷回忆、概念辨析与正反例辨认"} for node in nodes]
    overview_items = [
        {"label": "学习范围", "value": str(enrichment_data.get("learning_scope") or "覆盖当前复习清单中的全部学习节点，以及每个节点的核心概念、判断边界与证据依据。")},
        {"label": "学习方法", "value": str(enrichment_data.get("learning_method") or "先闭卷回忆，再揭示答案并进行会、模糊、不会自评；遇到不确定内容回到来源复核。")},
    ]
    scenes.append({"scene_id": "scene:review:overview", "kind": "intro", "page_role": "review_overview", "layout_recipe_id": "review_overview", "content_budget": {"min_chars": 80, "min_zones": 4}, "title": enrichment_data.get("course_title") or package.get("title") or "复习清单", "lead": enrichment_data.get("overview_lead") or "先独立回忆，再揭示答案并完成自评。", "blocks": [package.get("instructions") or "完成每道题的闭卷回忆后再揭示答案。"], "conclusion": "本课件的自评不会计入正式测评成绩。", "source_refs": [resource_id], "source_block_ids": overview_ids, "component_blocks": [{"schema_version": "4.0", "block_id": "review-overview", "component": "review_overview", "text": package.get("instructions") or "主动回忆训练", "items": overview_items, "node_items": node_items, "source_refs": refs(overview_ids)}]})
    for index, node in enumerate(nodes, 1):
        node_id = str(node.get("skill_node_id") or index)
        base = f"scene:review:node:{index}:{node_id}"
        recall = [item for item in (node.get("recall_questions") or []) if isinstance(item, dict)]
        distinction = [item for item in (node.get("distinction_questions") or []) if isinstance(item, dict)]
        examples = example_questions(node)
        for page_index, page_questions in enumerate(chunks(recall), 1):
            page_ids = tuple(block_by_question.get(str(question.get("question_id"))) for question in page_questions if block_by_question.get(str(question.get("question_id")))) or overview_ids
            scenes.append({"scene_id": f"{base}:recall:{page_index}", "kind": "practice", "page_role": "review_recall", "layout_recipe_id": "review_recall_grid", "title": f"{node.get('skill_node_name') or node_id}｜闭卷回忆（第{page_index}页）", "lead": "先在脑中作答；准备好后再显示答案。", "blocks": [], "conclusion": "根据答案标记会、模糊或不会。", "source_refs": [resource_id], "source_block_ids": list(page_ids), "component_blocks": [{"schema_version": "4.0", "block_id": f"{base}:recall:{page_index}:cards", "component": "review_recall_card", "text": "闭卷回忆", "items": page_questions, "source_refs": refs(list(page_ids))}]})
        for page_index, page_questions in enumerate(chunks(distinction), 1):
            page_ids = tuple(block_by_question.get(str(question.get("question_id"))) for question in page_questions if block_by_question.get(str(question.get("question_id")))) or overview_ids
            scenes.append({"scene_id": f"{base}:distinction:{page_index}", "kind": "practice", "page_role": "review_distinction", "layout_recipe_id": "review_distinction_grid", "title": f"{node.get('skill_node_name') or node_id}｜概念辨析（第{page_index}页）", "lead": "先判断陈述，再揭示纠正表述与依据。", "blocks": [], "conclusion": "把误区转化为下一次判断时的检查条件。", "source_refs": [resource_id], "source_block_ids": list(page_ids), "component_blocks": [{"schema_version": "4.0", "block_id": f"{base}:distinction:{page_index}:cards", "component": "review_distinction_card", "text": "概念辨析", "items": page_questions, "source_refs": refs(list(page_ids))}]})
        example_ids = tuple(block_by_question.get(str(question.get("question_id"))) for question in examples if block_by_question.get(str(question.get("question_id")))) or overview_ids
        component = {"schema_version": "4.0", "block_id": f"{base}:example", "component": "review_example_card" if examples else "review_reflection", "text": "正反例辨认" if examples else "当前 Evidence 不足以形成单一明确边界。", "source_refs": refs(list(example_ids))}
        if examples:
            component["items"] = examples
        else:
            component["reason"] = next((item.get("reason") for item in (node.get("omitted_slots") or []) if str(item.get("local_id")) in {"example-1", "example-2"}), "NO_EXPLICIT_CONCEPT_BOUNDARY")
        scenes.append({"scene_id": f"{base}:example", "kind": "recap", "page_role": "review_example", "layout_recipe_id": "review_example_focus", "title": f"{node.get('skill_node_name') or node_id}｜正反例与边界", "lead": "辨认决定性差异，再以 Evidence 校准理解边界。", "blocks": [], "conclusion": summaries.get(node_id) or "完成本节点全部实际题目的自评后，即可形成低置信度掌握记录。", "source_refs": [resource_id], "source_block_ids": list(example_ids), "component_blocks": [component]})
        knowledge_summary = str(node.get("knowledge_summary") or summaries.get(node_id) or "").strip()
        summary_id = block_by_summary.get(node_id)
        if knowledge_summary and summary_id:
            scenes.append({"scene_id": f"{base}:summary", "kind": "recap", "page_role": "review_node_summary", "layout_recipe_id": "review_node_summary", "content_budget": {"min_chars": 100, "min_zones": 2}, "title": f"{node.get('skill_node_name') or node_id}｜知识小结", "lead": "把闭卷回忆、概念辨析与边界判断收束为本节点的可执行复盘。", "blocks": [knowledge_summary], "conclusion": "完成本页小结后，再进入下一个节点的三组固定练习。", "source_refs": [resource_id], "source_block_ids": [summary_id], "component_blocks": [{"schema_version": "4.0", "block_id": f"{base}:summary", "component": "review_node_summary", "node_name": str(node.get("skill_node_name") or node_id), "text": knowledge_summary, "source_refs": refs([summary_id])}]})
    completion_lead = str(enrichment_data.get("completion_lead") or "回顾每个节点的自评，再选择下一步。")
    completion_message = str(enrichment_data.get("completion_message") or "出现不会时返回对应节点；两项及以上模糊时重新闭卷作答；全部会时进入实操或分阶测试。")
    overall_summary = str(enrichment_data.get("overall_summary") or "本轮复习把各节点的核心概念、判断边界与证据依据串联起来：先闭卷回忆，再通过概念辨析和正反例辨认检查理解是否能够迁移。完成自评后，优先回到标记为模糊或不会的题目，重新核对对应来源与前提条件。")
    scenes.append({"scene_id": "scene:review:summary", "kind": "recap", "page_role": "summary_action", "layout_recipe_id": "recap_dashboard", "content_budget": {"min_chars": 140, "min_zones": 3}, "title": "复习完成与下一步", "lead": completion_lead, "blocks": [], "conclusion": completion_message, "source_refs": [resource_id], "source_block_ids": overview_ids, "component_blocks": [{"schema_version": "4.0", "block_id": "review-completion", "component": "review_completion", "text": "节点完成情况", "overall_summary": overall_summary, "items": [{"node_id": str(node.get("skill_node_id") or index), "label": str(node.get("skill_node_name") or node.get("skill_node_id") or index)} for index, node in enumerate(nodes, 1)], "source_refs": refs(overview_ids)}]})
    # Preserve the ordinary workflow's scene contract even though the visible
    # learning material is renderer-owned structured cards rather than prose
    # zones.  These fields keep storyboard/source hard gates and the existing
    # scene composer on the same base pipeline.
    objective_id = f"objective:{resource_id}"
    for scene in scenes:
        ids = list(scene.get("source_block_ids") or overview_ids)
        scene["objective_ids"] = [objective_id]
        scene["source_map"] = {"title": [ids[:1]], "lead": [ids[:1]], "blocks": [ids[:1]], "conclusion": [ids[-1:]]}
        if not scene.get("blocks"):
            scene["blocks"] = [str(scene.get("lead") or "完成当前主动回忆练习。")]
        if scene.get("kind") == "practice":
            scene["steps"] = ["完成本页题目后揭示答案并进行自评。"]
            scene["source_map"]["steps"] = [ids[:1]]
    return scenes


def compose_scenes(
    snapshots: list[dict[str, Any]], plan: CoursewareSpec | None = None,
    *, learning_design: CoursewareLearningDesign | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    review_scenes = _review_practice_scenes(snapshots, getattr(plan, "review_practice_enrichment", None) if plan else None)
    if review_scenes is not None:
        return review_scenes, []
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
