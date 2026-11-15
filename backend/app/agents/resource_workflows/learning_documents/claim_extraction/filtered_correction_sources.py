"""V2 correction Claim targets; full packages remain in ordinary review/storage."""

from app.core.learning_documents.correction_package import (
    CORRECTION_AUDIT_GUIDANCE, correction_audit_source, validated_correction_package,
)
from app.models.reviews.claim_extraction import content_digest, digest
from app.models.reviews.claims import FILTERED_CORRECTION_SOURCE

VERSION = "correction-content-sources-v2"
PROMPT_VERSION = FILTERED_CORRECTION_SOURCE
EXCLUDED_LEAF_KEYS = frozenset({"mistaken_view", "incorrect_statement"})
GUIDANCE = CORRECTION_AUDIT_GUIDANCE + """
Claim来源筛选correction-content-sources-v2：mistaken_view、incorrect_statement已从抽取目标排除。
它们是待纠正的命题，不是作者认可的技术结论，必要时仅出现在read_only_related_fields。
read_only_related_fields只帮助理解目标，不是证据，也不得从中生成Claim或引用source_text。
只从本批target_units复制逐字原文，source_text不得跨字段、拼接或改写。
纯假设的文档、参数、数量不核验是否真实发生；scenario字段中的独立技术事实仍须核验。
解释/答案中的技术结论必须结合关联题设保留条件；不能因字段是答案就认为正确。
claim_text可表达“在题设条件下”的完整含义，source_text仍须逐字来自当前目标字段。
"""


def frozen_extension():
    return {"version": VERSION, "guidance_hash": digest(GUIDANCE),
            "field_policy_hash": digest({"excluded_leaf_keys": sorted(EXCLUDED_LEAF_KEYS),
                                       "context_policy": "related-correction-fields-v1"})}


def _related_paths(path):
    if ".error_patterns[" in path and path.endswith(".explanation"):
        return [path.rsplit(".", 1)[0] + ".mistaken_view"]
    if ".comparisons[" in path:
        return [path.rsplit(".", 1)[0] + ".incorrect_statement"]
    example = "content.unit.worked_example."
    if path.startswith(example):
        return [example + "scenario", example + "task"]
    exercises = "content.unit.exercises."
    if path.startswith(exercises):
        group = path[len(exercises):].split(".", 1)[0]
        return [exercises + group + ".scenario", exercises + group + ".question"]
    return []


def build_source(resource, *, version=VERSION, prompt_version=PROMPT_VERSION, excluded_roots=()):
    from .resource_sources import AuditSource

    class FilteredCorrectionSource(AuditSource):
        def classify(self, candidates):
            for candidate in candidates:
                matches = [f for f in self.fields if f["start"] <= candidate.source_start
                           and candidate.source_end <= f["end"]]
                if (len(matches) != 1 or candidate.source_end <= candidate.source_start
                        or self.text[candidate.source_start:candidate.source_end] != candidate.source_text):
                    raise ValueError("filtered correction Claim must quote one target field, not context")
            return candidates

    package = validated_correction_package(resource)
    if version == VERSION and package.schema_version != "correction-package-v1":
        raise ValueError("v2 correction source cannot read compact package")
    original = correction_audit_source(package)
    parts, fields, excluded, bindings = [], [], [], {}
    available = {f.path for f in original.fields}
    offset = 0
    for field in original.fields:
        proposition = field.path.rsplit(".", 1)[-1] in EXCLUDED_LEAF_KEYS
        display_only = any(field.path == root or field.path.startswith(root + "[")
                           or field.path.startswith(root + ".") for root in excluded_roots)
        if proposition or display_only:
            excluded.append({"path": field.path, "role": field.role,
                             "reason": "exercise_proposition" if proposition else "display_only"})
            continue
        value = original.text[field.start:field.end]
        header = f"## {field.path} [{field.role}]\n\n"
        start = offset + len(header)
        parts.extend((header, value, "\n\n"))
        fields.append(dict(path=field.path, role=field.role, start=start, end=start + len(value)))
        related = [p for p in _related_paths(field.path) if p in available and p != field.path]
        if related:
            bindings[field.path] = related
        offset = start + len(value) + 2
    text = "".join(parts)
    snapshot = {"version": version, "prompt_version": prompt_version,
                "resource_id": resource.resource_id, "resource_version": resource.version,
                "public_content_hash": content_digest(resource.content_text or ""),
                "payload_hash": package.payload_hash, "audit_content_hash": content_digest(text),
                "fields": fields, "question_bindings": {},
                "excluded_fields": excluded, "context_bindings": bindings}
    return FilteredCorrectionSource(text, fields, snapshot, prompt_version)


def related_context(resource, source, target_fields):
    """Read-only snippets are selected by server-owned field relationships."""
    original = correction_audit_source(validated_correction_package(resource))
    present = {f["path"] for f in target_fields}
    bindings = source.snapshot["context_bindings"]
    wanted = {path for target in present for path in bindings.get(target, [])} - present
    return [{"path": f.path, "role": f.role, "text": original.text[f.start:f.end]}
            for f in original.fields if f.path in wanted]
