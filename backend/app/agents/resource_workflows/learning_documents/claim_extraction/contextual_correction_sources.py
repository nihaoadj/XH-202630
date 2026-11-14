"""Frozen V4 correction targets and read-only teaching context.

The package and public Markdown are unchanged. Field selection is deterministic;
semantic classification inside explanations remains the extractor's responsibility.
"""

from app.core.learning_documents.correction_package import (
    correction_audit_source, validated_correction_package,
)
from app.models.reviews.claim_extraction import content_digest, digest
from app.models.reviews.claims import CONTEXTUAL_CORRECTION_SOURCE
from .compact_correction_sources import DISPLAY_ROOTS
from .filtered_correction_sources import EXCLUDED_LEAF_KEYS
from .resource_sources import AuditSource

VERSION = "correction-content-sources-v4"
PROMPT_VERSION = CONTEXTUAL_CORRECTION_SOURCE
INPUT_VERSION = "correction-context-input-v1"
EXERCISE_TARGETS = frozenset({"reference_answer", "explanation"})
GUIDANCE = """纠错包来源 correction-content-sources-v4：只从 target_units 抽取。
structured_context.unit_fields 将本批原文区间绑定到字段路径与角色，区间以对应 unit.text 为准。
所有 read_only_context/read_only_related_fields 仅用于理解，不是抽取目标或事实证据。
练习仅抽取 reference_answer、explanation；情境和问题是假设上下文，不核验其真实发生。
错误模式的 mistaken_view、正误对照的 incorrect_statement 是待纠正命题，不代表作者认可。
本规则适用于所有目标，包括概念补救、正误对照、错误解释、参考答案、分层反馈和总结：
被引用或被否定的错误观点、假设事件、反例条件本身标 non_factual；不能脱离否定关系把错误引文单独标 factual。
资源实际认可的技术断言即使错误、缺证或出现在答案中，仍必须标 factual 并交给 Judge 核验。
教学要求标 instructional，标题/过渡语按语义分类；不能因整段包含反例、假设或教学动作而漏掉独立知识结论。
claim_text 必须保留条件、主体、否定和纠正关系，可用只读题设消歧，但不可将假设写成已发生的事实。
source_text 必须逐字复制当前目标字段内连续原文，不拼接字段，不从上下文补抽，不改写原文。
无法保留充分条件或无法消歧时使用现有 uncertain 路径，不猜测、不假装通过。
"""


def frozen_extension():
    return {"version": VERSION, "guidance_hash": digest(GUIDANCE),
            "field_policy_hash": digest({"excluded_roots": DISPLAY_ROOTS,
                "excluded_leaf_keys": sorted(EXCLUDED_LEAF_KEYS),
                "exercise_targets": sorted(EXERCISE_TARGETS),
                "context_policy": INPUT_VERSION})}


def _role(path):
    key = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if key == "reference_answer":
        return "answer"
    if key == "correct_statement":
        return "correct_statement"
    if ".concept_repair[" in path:
        return "concept_label" if key == "point" else "explanation"
    if path.startswith("content.layered_feedback."):
        return "feedback"
    if path == "content.summary":
        return "summary"
    return "explanation"


def _related_paths(path):
    if ".error_patterns[" in path:
        return [path.rsplit(".", 1)[0] + ".mistaken_view"]
    if ".comparisons[" in path:
        base = path.rsplit(".", 1)[0]
        return [base + ".incorrect_statement", base + ".correct_statement"]
    if path.startswith("content.unit.exercises."):
        base = path.rsplit(".", 1)[0]
        return [base + ".scenario", base + ".question"]
    return []


class ContextualCorrectionSource(AuditSource):
    def classify(self, candidates):
        for candidate in candidates:
            matches = [f for f in self.fields if f["start"] <= candidate.source_start
                       < candidate.source_end <= f["end"]]
            if (len(matches) != 1 or
                    self.text[candidate.source_start:candidate.source_end] != candidate.source_text):
                raise ValueError("contextual correction Claim must quote one target field")
        return candidates


def build_source(resource):
    package = validated_correction_package(resource)
    if package.schema_version != "correction-package-v2":
        raise ValueError("contextual correction source requires compact package")
    original = correction_audit_source(package)
    parts, fields, excluded, bindings = [], [], [], {}
    offset = 0
    for field in original.fields:
        key = field.path.rsplit(".", 1)[-1].split("[", 1)[0]
        reason = None
        if any(field.path == root or field.path.startswith(root + "[")
               or field.path.startswith(root + ".") for root in DISPLAY_ROOTS):
            reason = "display_only"
        elif key in EXCLUDED_LEAF_KEYS:
            reason = "exercise_proposition"
        elif field.path.startswith("content.unit.exercises.") and key not in EXERCISE_TARGETS:
            reason = "exercise_context" if key in {"scenario", "question"} else "exercise_instruction"
        if reason:
            excluded.append({"path": field.path, "role": field.role, "reason": reason})
            continue
        role = _role(field.path)
        value = original.text[field.start:field.end]
        header = f"## {field.path} [{role}]\n\n"
        start = offset + len(header)
        parts.extend((header, value, "\n\n"))
        fields.append({"path": field.path, "role": role, "start": start, "end": start + len(value)})
        bindings[field.path] = [p for p in _related_paths(field.path) if p != field.path]
        offset = start + len(value) + 2
    text = "".join(parts)
    snapshot = {"version": VERSION, "prompt_version": PROMPT_VERSION,
        "resource_id": resource.resource_id, "resource_version": resource.version,
        "public_content_hash": content_digest(resource.content_text or ""),
        "payload_hash": package.payload_hash, "audit_content_hash": content_digest(text),
        "fields": fields, "question_bindings": {}, "excluded_fields": excluded,
        "context_bindings": bindings, "input_version": INPUT_VERSION}
    return ContextualCorrectionSource(text, fields, snapshot, PROMPT_VERSION)


def related_context(resource, source, target_fields):
    original = correction_audit_source(validated_correction_package(resource))
    present = {f["path"] for f in target_fields}
    wanted = {p for f in target_fields for p in source.snapshot["context_bindings"].get(f["path"], [])} - present
    return [{"path": f.path, "role": f.role, "text": original.text[f.start:f.end]}
            for f in original.fields if f.path in wanted]
