"""Bind readable frozen content; a reference ID alone is never evidence text."""
from app.models.courseware.content_review import EvidenceBundleV1, EvidenceV1, FieldLocatorV1, canonical_json, json_hash

COURSE_RULE = "只呈现冻结来源。复习先闭卷、揭示答案、自评；自评不等于正式成绩或已经掌握。实操按准备、步骤、验证、复盘顺序，不执行代码，不提供自动运行、评分或不存在的按钮。"


def bind_evidence(snapshot, source_key):
    entries = []
    def add(eid, kind, text, owner, tokens):
        entries.append(EvidenceV1(evidence_id=eid, kind=kind, text=text,
                                 source=FieldLocatorV1(space="source", owner_id=owner, tokens=tokens), value_hash=json_hash(text)))
    package = snapshot[source_key]
    if "node_blocks" in package:
        for node in package["node_blocks"]:
            owner = node["skill_node_id"]
            add(f"node:{owner}", "source_content", node["knowledge_summary"], owner, ["knowledge_summary"])
            questions = node["recall_questions"] + node["distinction_questions"] + (node.get("example_recognition_questions") or ([node["example_recognition"]] if node.get("example_recognition") else []))
            for question in questions:
                add(f"answer:{question['question_id']}", "source_answer", canonical_json(question), owner, [question["question_id"]])
    else:
        for phase in ("preparation", "verification", "reflection"):
            add(f"phase:{phase}", "source_content", canonical_json(package[phase]), phase, [phase])
        for step in package["practice"]["steps"]:
            add(f"step:{step['step_id']}", "source_content", canonical_json(step), step["step_id"], ["practice", step["step_id"]])
    for ref in snapshot.get("content_review_evidence") or []:
        if ref.get("text") and (ref.get("evidence_id") or ref.get("reference_id")):
            if ref.get("value_hash") != json_hash(ref["text"]):
                raise ValueError("frozen reference text hash mismatch")
            rid = ref.get("evidence_id") or ref["reference_id"]
            add(f"ref:{rid}", "source_content", ref["text"], snapshot["resource_id"], ["evidence", rid])
    add("course:rules", "course_rule", COURSE_RULE, snapshot["resource_id"], ["course_rules"])
    return EvidenceBundleV1(items=entries)
