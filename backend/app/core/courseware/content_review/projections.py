"""Independent output oracle. This module never imports/calls composition."""
import re
from app.core.courseware.content_review.inventory import at
from app.models.courseware.content_review import ContentItemV1, ContentReviewBlocked, FieldLocatorV1, json_hash

SCENE_KEYS = frozenset("scene_id kind page_role layout_recipe_id content_budget title lead blocks conclusion source_refs source_block_ids component_blocks objective_ids source_map steps options answer feedback key_question practice_variant required_zones allowed_component_ids practice_json_schema_version practice_json_subject title_source_json_path llm_enriched".split())
BLOCK_KEYS = frozenset("schema_version block_id component text source_refs items node_items overall_summary node_name reason label presentation_role steps source_json_path evidence_json_path language code purpose pedagogical_role".split())
VISIBLE = ("title", "lead", "blocks", "conclusion", "steps", "options", "answer", "feedback", "key_question")


class ProjectionOracle:
    def __init__(self, document):
        if set(document) - {"schema_version", "title", "scenes", "design", "event_context"}:
            raise ContentReviewBlocked("unknown document field")
        self.document, self.manifest, self.covered = document, [], set()
        for scene in document["scenes"]:
            if set(scene) - SCENE_KEYS:
                raise ContentReviewBlocked("unknown scene field")
            for block in scene.get("component_blocks", []):
                if set(block) - BLOCK_KEYS:
                    raise ContentReviewBlocked("unknown component field")
                from app.core.courseware.components import is_registered_component
                if not is_registered_component(block.get("component"), block.get("schema_version")):
                    raise ContentReviewBlocked("unregistered projection component")

    def expect(self, path, expected, origin="source", owner="course", item_id=None):
        try:
            actual = at(self.document, path)
        except (KeyError, IndexError, TypeError) as exc:
            raise ContentReviewBlocked("missing projection target") from exc
        if actual != expected:
            raise ContentReviewBlocked("projection value/order mismatch")
        self.covered.add(tuple(path))
        self.manifest.append(ContentItemV1(item_id=f"target:{json_hash(path)[:24]}", owner_id=owner, origin=origin,
            source=FieldLocatorV1(space="candidate" if origin == "ai" else "source" if origin == "source" else "template", owner_id=owner, tokens=[item_id or str(path[-1])]),
            targets=[FieldLocatorV1(space="document", owner_id=owner, tokens=path)], value_hash=json_hash(expected),
            dependency_ids=[item_id] if item_id and origin in {"ai", "user"} else []))

    def finish(self):
        required = [("title",)]
        for i, scene in enumerate(self.document["scenes"]):
            required.extend(("scenes", i, k) for k in VISIBLE if k in scene and scene[k] is not None)
            for j, block in enumerate(scene.get("component_blocks", [])):
                required.extend(("scenes", i, "component_blocks", j, k) for k in block if k not in {"source_refs", "schema_version", "block_id", "component", "source_json_path", "evidence_json_path", "presentation_role", "pedagogical_role"})
        if any(p not in self.covered for p in required):
            raise ContentReviewBlocked("unclassified consumed output")
        return {"manifest": self.manifest, "document_hash": json_hash({k: v for k, v in self.document.items() if k != "event_context"})}


def _title(o, snapshot, design, candidate):
    base = design.get("user_title") or candidate.get("course_title") or snapshot.get("topic") or "学习主题"
    label = snapshot["resource_type"]
    title = base if label in base else f"{label}｜{base.strip()}"
    o.expect(["title"], title, "user" if design.get("user_title") else "ai" if candidate else "derived", item_id="user:course:title" if design.get("user_title") else "ai:course:course_title")


def review_projection(snapshot, candidate, document, design=None):
    p = snapshot["review_practice_payload"]
    o = ProjectionOracle(document)
    # The caller validates root title independently with its frozen user input.
    if design is not None:
        _title(o, snapshot, design, candidate)
    else:
        o.expect(["title"], document["title"], "derived")
    summaries = {n["skill_node_id"]: n["summary"] for n in candidate.get("node_summaries", [])}
    expected = []
    overview_lead = candidate.get("overview_lead") or "先独立回忆，再揭示答案并完成自评。"
    expected.append(("scene:review:overview", {
        "title": candidate.get("course_title") or p["title"] or "复习清单", "lead": overview_lead,
        "blocks": [p["instructions"] or "完成每道题的闭卷回忆后再揭示答案。"], "conclusion": "本课件的自评不会计入正式测评成绩。",
    }, [{"text": p["instructions"] or "主动回忆训练", "items": [
        {"label": "学习范围", "value": candidate.get("learning_scope") or "覆盖当前复习清单中的全部学习节点，以及每个节点的核心概念、判断边界与证据依据。"},
        {"label": "学习方法", "value": candidate.get("learning_method") or "先闭卷回忆，再揭示答案并进行会、模糊、不会自评；遇到不确定内容回到来源复核。"}],
        "node_items": [{"label": n["skill_node_name"], "value": "闭卷回忆、概念辨析与正反例辨认"} for n in p["node_blocks"]]}], "course"))
    for index, node in enumerate(p["node_blocks"], 1):
        owner = node["skill_node_id"]; base = f"scene:review:node:{index}:{owner}"; name = node["skill_node_name"]
        for collection, suffix, label, lead, conclusion in (
            (node["recall_questions"], "recall", "闭卷回忆", "先在脑中作答；准备好后再显示答案。", "根据答案标记会、模糊或不会。"),
            (node["distinction_questions"], "distinction", "概念辨析", "先判断陈述，再揭示纠正表述与依据。", "把误区转化为下一次判断时的检查条件。")):
            for start in range(0, len(collection), 2):
                expected.append((f"{base}:{suffix}:{start//2+1}", {"title": f"{name}｜{label}（第{start//2+1}页）", "lead": lead, "blocks": [lead], "conclusion": conclusion,
                    "steps": ["完成本页题目后揭示答案并进行自评。"]}, [{"text": label, "items": collection[start:start+2]}], owner))
        examples = node.get("example_recognition_questions") or ([node["example_recognition"]] if node.get("example_recognition") else [])
        component = {"text": "正反例辨认", "items": examples} if examples else {"text": "当前 Evidence 不足以形成单一明确边界。", "reason": next((n["reason"] for n in node["omitted_slots"] if n["local_id"] in {"example-1", "example-2"}), "NO_EXPLICIT_CONCEPT_BOUNDARY")}
        lead = "辨认决定性差异，再以 Evidence 校准理解边界。"
        expected.append((f"{base}:example", {"title": f"{name}｜正反例与边界", "lead": lead, "blocks": [lead],
            "conclusion": summaries.get(owner) or "完成本节点全部实际题目的自评后，即可形成低置信度掌握记录。"}, [component], owner))
        expected.append((f"{base}:summary", {"title": f"{name}｜知识小结", "lead": "把闭卷回忆、概念辨析与边界判断收束为本节点的可执行复盘。", "blocks": [node["knowledge_summary"].strip()], "conclusion": "完成本页小结后，再进入下一个节点的三组固定练习。"}, [{"node_name": name, "text": node["knowledge_summary"].strip()}], owner))
    lead = candidate.get("completion_lead") or "回顾每个节点的自评，再选择下一步。"
    expected.append(("scene:review:summary", {"title": "复习完成与下一步", "lead": lead, "blocks": [lead],
        "conclusion": candidate.get("completion_message") or "出现不会时返回对应节点；两项及以上模糊时重新闭卷作答；全部会时进入实操或分阶测试。"}, [{"text": "节点完成情况",
        "overall_summary": candidate.get("overall_summary") or "本轮复习把各节点的核心概念、判断边界与证据依据串联起来：先闭卷回忆，再通过概念辨析和正反例辨认检查理解是否能够迁移。完成自评后，优先回到标记为模糊或不会的题目，重新核对对应来源与前提条件。",
        "items": [{"node_id": n["skill_node_id"], "label": n["skill_node_name"]} for n in p["node_blocks"]]}], "course"))
    if [s["scene_id"] for s in document["scenes"]] != [s[0] for s in expected]:
        raise ContentReviewBlocked("review page omitted/reordered")
    for i, (_, values, components, owner) in enumerate(expected):
        scene = document["scenes"][i]
        expected_id = expected[i][0]
        if expected_id == "scene:review:overview":
            role, kind, recipe = "review_overview", "intro", "review_overview"
        elif expected_id == "scene:review:summary":
            role, kind, recipe = "summary_action", "recap", "recap_dashboard"
        elif ":recall:" in expected_id:
            role, kind, recipe = "review_recall", "practice", "review_recall_grid"
        elif ":distinction:" in expected_id:
            role, kind, recipe = "review_distinction", "practice", "review_distinction_grid"
        elif expected_id.endswith(":example"):
            role, kind, recipe = "review_example", "recap", "review_example_focus"
        else:
            role, kind, recipe = "review_node_summary", "recap", "review_node_summary"
        for key, value in (("page_role", role), ("kind", kind), ("layout_recipe_id", recipe)):
            o.expect(["scenes", i, key], value, "derived", owner)
        expected_component = {"review_overview": "review_overview", "review_recall": "review_recall_card", "review_distinction": "review_distinction_card", "review_example": "review_example_card" if components[0].get("items") else "review_reflection", "review_node_summary": "review_node_summary", "summary_action": "review_completion"}.get(role)
        for key, value in values.items():
            is_ai = candidate and ((i == 0 and key in {"title", "lead"}) or (i == len(expected)-1 and key in {"lead", "conclusion"}) or (expected_id.endswith(":example") and key == "conclusion" and owner in summaries))
            origin = "ai" if is_ai else "source" if key == "blocks" else "template"
            field = ({"title": "course_title", "lead": "overview_lead"}.get(key) if i == 0 else {"lead": "completion_lead", "conclusion": "completion_message"}.get(key) if i == len(expected)-1 else "summary")
            o.expect(["scenes", i, key], value, origin, owner, f"ai:{owner}:{field}" if is_ai else None)
        actual = document["scenes"][i].get("component_blocks", [])
        if len(actual) != len(components):
            raise ContentReviewBlocked("review component count")
        for j, component in enumerate(components):
            if actual[j]["component"] != expected_component:
                raise ContentReviewBlocked("review component binding changed")
            for key, value in component.items():
                origin = "ai" if candidate and key == "overall_summary" else "derived" if key in {"items", "node_items"} else "source" if role in {"review_overview", "review_node_summary"} and key in {"text", "node_name"} else "template"
                o.expect(["scenes", i, "component_blocks", j, key], value, origin, owner, "ai:course:overall_summary" if origin == "ai" else None)
            question_blocks = {b["review_question_id"]: b["block_id"] for b in snapshot["blocks"] if b.get("review_question_id")}
            ids = [question_blocks[q["question_id"]] for q in component.get("items", []) if q.get("question_id")]
            if role == "review_node_summary":
                ids = [next(b["block_id"] for b in snapshot["blocks"] if b.get("kind") == "review_summary" and b.get("skill_node_id") == owner)]
            if not ids:
                ids = [next(iter(question_blocks.values()))]
            o.expect(["scenes", i, "component_blocks", j, "source_refs"], [{"source_resource_id": snapshot["resource_id"], "source_block_ids": ids}], "derived", owner)
            o.expect(["scenes", i, "source_block_ids"], ids, "derived", owner)
            expected_map = {"title": [ids[:1]], "lead": [ids[:1]], "blocks": [ids[:1]], "conclusion": [ids[-1:]]}
            if "steps" in values:
                expected_map["steps"] = [ids[:1]]
            o.expect(["scenes", i, "source_map"], expected_map, "derived", owner)
        if i == 0 and candidate:
            for j, key in enumerate(("learning_scope", "learning_method")):
                o.expect(["scenes", i, "component_blocks", 0, "items", j, "value"], candidate[key], "ai", "course", f"ai:course:{key}")
    return o.finish()


def practice_projection(snapshot, design, candidate, document):
    p = snapshot["practice_guide_payload"]; o = ProjectionOracle(document); _title(o, snapshot, design, candidate)
    slots = design["learning_design"]["storyboard"]["scenes"]
    subjects = [s.get("practice_json_subject") for s in document["scenes"]]
    required_subjects = [None, "preparation", *[f"practice.steps.{s['step_id']}" for s in p["practice"]["steps"]], "verification", "reflection"]
    if subjects != required_subjects or not document["scenes"] or document["scenes"][0].get("page_role") != "cover":
        raise ContentReviewBlocked("incomplete practice phases")
    if [s["scene_id"] for s in document["scenes"]] != [s["scene_id"] for s in slots]:
        raise ContentReviewBlocked("practice page omitted/reordered")
    steps = {s["step_id"]: s for s in p["practice"]["steps"]}
    seen = []
    for i, scene in enumerate(document["scenes"]):
        path = ["scenes", i]; subject = scene.get("practice_json_subject"); components = scene.get("component_blocks", [])
        for key in ("kind", "page_role", "layout_recipe_id"):
            o.expect([*path, key], slots[i][key], "derived")
        selected_blocks = [b for b in snapshot["blocks"] if b["block_id"] in slots[i]["source_block_ids"]]
        bound_step = next((b.get("practice_step_id") for b in selected_blocks if b.get("practice_step_id")), None)
        bound_phase = next((b.get("practice_phase_id") for b in selected_blocks if b.get("practice_phase_id")), None)
        bound_subject = f"practice.steps.{bound_step}" if bound_step else {"prepare": "preparation", "verify": "verification", "reflect": "reflection"}.get(bound_phase)
        if slots[i]["kind"] == "practice" and subject != bound_subject:
            raise ContentReviewBlocked("practice phase/step binding changed")
        if subject and subject.startswith("practice.steps."):
            owner = subject.removeprefix("practice.steps.")
            if owner not in steps:
                raise ContentReviewBlocked("unknown practice step")
            seen.append(owner); s = steps[owner]; instruction = s["instruction_text"].strip(); verification = s["verification"].strip()
            values = {"title": f"步骤 {owner.removeprefix('step-')}｜{s['title']}", "lead": instruction, "blocks": [instruction, f"完成验证：{verification}"], "conclusion": f"完成本步骤的验证：{verification}", "steps": []}
            blocks = [{"text": instruction}, *[{"text": b["purpose"] or "代码", "language": b["language"], "code": b["code"], "purpose": b["purpose"]} for b in s["code_blocks"]], {"text": verification, "label": "完成验证"}]
        elif subject in {"preparation", "verification", "reflection"}:
            owner = subject; phase = p[subject]; items = list(phase.get("items") or phase.get("checklist") or [])
            label = {"preparation": "准备阶段", "verification": "验证阶段", "reflection": "复盘与小结"}[subject]
            values = {"title": label, "lead": phase["goal"], "blocks": items if subject != "reflection" else [phase["summary"]], "conclusion": f"完成{label}后，再进入下一阶段。", "steps": items}
            blocks = [{"text": phase["goal"], "label": {"preparation": "阶段目标", "verification": "验证目标", "reflection": "复盘目标"}[subject]},
                      {"text": "准备项目" if subject == "preparation" else "最终检查项", "steps": items} if subject != "reflection" else {"text": phase["summary"], "label": "复盘小结"}]
        elif scene.get("page_role") == "cover":
            owner = "cover"; cover = candidate.get("practice_cover")
            if cover:
                values = {"title": cover["cover_title"], "lead": cover["cover_lead"].strip(), "blocks": [f"学习目标：{cover['learning_goal'].strip()}", f"学习方法：{cover['learning_method'].strip()}", f"完成标准：{cover['completion_standard'].strip()}"], "conclusion": f"完成标准：{cover['completion_standard'].strip()}"}
                blocks = [{"text": cover["learning_goal"], "label": "学习目标"}, {"text": cover["learning_method"].strip(), "label": "学习方法"}]
            else:
                topic = re.sub(r"\s*(?:学习资源包|资源包)\s*", " ", str(snapshot.get("topic") or "")).strip()
                title = topic if topic.endswith("实操指南") else f"实操指南 | {topic}" if topic else "实操指南 | 互动课件"
                values = {"title": candidate.get("course_title") or title, "lead": "先了解本课件的目标与完成路径，再进入对应的来源步骤。", "blocks": [f"学习目标：围绕{snapshot.get('topic') or '这份冻结资源'}完成从准备、操作到验证的完整闭环。", "学习方法：先确认环境与前置条件，再按来源页面逐步执行操作，并在每一步核对验证结果。", "完成标准：能够依据来源完成关键步骤，解释结果，并定位仍需复习的环节。"]}
                # Cover conclusion uses the last selected frozen paragraph.
                selected_texts = [b["text"] for b in selected_blocks]
                paragraphs = []
                for text in selected_texts:
                    parts = [text.strip()] if text.strip().startswith("```") else [s.strip() for line in text.split("\n") if line.strip() for s in re.split(r"(?<=[。！？；])\s*", line.strip(" #-\t")) if s.strip()][:12]
                    paragraphs.extend(parts)
                paragraphs = paragraphs[:10]
                values["conclusion"] = f"页面结论：{paragraphs[-1]}下一步请把本页判断带入后续场景，通过操作或检查验证理解。"
                blocks = [{"text": v} for v in values["blocks"]]
        else:
            raise ContentReviewBlocked("unmapped practice page")
        for key, value in values.items():
            ai = owner == "cover" and candidate
            field = {"title": "cover_title", "lead": "cover_lead", "conclusion": "completion_standard"}.get(key)
            iid = f"ai:cover:{field}" if ai and field and candidate.get("practice_cover") else "ai:course:course_title" if ai and key == "title" else None
            o.expect([*path, key], value, "ai" if ai and key != "blocks" else "derived" if ai else "source", owner, iid)
            if ai and key == "blocks" and candidate.get("practice_cover"):
                for index, field_name in enumerate(("learning_goal", "learning_method", "completion_standard")):
                    o.expect([*path, key, index], value[index], "ai", owner, f"ai:cover:{field_name}")
        if "key_question" in scene:
            o.expect([*path, "key_question"], slots[i]["key_question"], "derived", owner)
        if len(blocks) != len(components):
            raise ContentReviewBlocked("practice component count")
        expected_components = (["key_point", *["code_block"]*len(steps[owner]["code_blocks"]), "callout"] if owner in steps else
            ["key_point", "steps" if owner != "reflection" else "callout"] if owner != "cover" else
            ["key_point", "callout"] if candidate.get("practice_cover") else ["callout", "key_point", "key_point"])
        if [b["component"] for b in components] != expected_components:
            raise ContentReviewBlocked("practice component binding changed")
        for j, block in enumerate(blocks):
            for key, value in block.items():
                ai = owner == "cover" and candidate and key == "text"
                field = "learning_goal" if j == 0 else "learning_method"
                o.expect([*path, "component_blocks", j, key], value, "ai" if ai else "template" if key == "label" else "source", owner, f"ai:cover:{field}" if ai else None)
            expected_ids = [b["block_id"] for b in selected_blocks]
            if owner == "cover" and not candidate.get("practice_cover"):
                expected_ids = [expected_ids[min(j, len(expected_ids)-1)]]
            o.expect([*path, "component_blocks", j, "source_refs"], [{"source_resource_id": snapshot["resource_id"], "source_block_ids": expected_ids}], "derived", owner)
        o.expect([*path, "source_block_ids"], [b["block_id"] for b in selected_blocks], "derived", owner)
    if seen != list(steps):
        raise ContentReviewBlocked("practice steps reordered/truncated")
    return o.finish()
