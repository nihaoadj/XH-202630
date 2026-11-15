"""Resource-specific target selection; shared exact field/context assembly."""

from dataclasses import dataclass

from app.models.reviews.claim_extraction import content_digest
from .input_context import VERSION
from .resource_sources import AuditSource
from app.models.reviews.claims import (
    UNIFIED_ASSESSMENT_SOURCE,
    UNIFIED_CHECKLIST_SOURCE,
    UNIFIED_CORRECTION_SOURCE,
    UNIFIED_PRACTICE_SOURCE,
    UNIFIED_PRACTICE_SOURCE_V2,
    UNIFIED_PRACTICE_SOURCE_V3,
    UNIFIED_PRACTICE_SOURCE_V4,
    UNIFIED_PRACTICE_SOURCE_V5,
)

MARKERS = {
    "分阶测试题": UNIFIED_ASSESSMENT_SOURCE,
    "复习清单": UNIFIED_CHECKLIST_SOURCE,
    "个性化纠错训练包": UNIFIED_CORRECTION_SOURCE,
    "实操指南": UNIFIED_PRACTICE_SOURCE,
}


@dataclass(frozen=True)
class Field:
    path: str
    role: str
    text: str


class UnifiedSource(AuditSource):
    def classify(self, candidates):
        # Role semantics stay model-owned; positional/type boundaries are deterministic.
        for candidate in candidates:
            matches = [
                f
                for f in self.fields
                if f["start"]
                <= candidate.source_start
                < candidate.source_end
                <= f["end"]
            ]
            if (
                len(matches) != 1
                or self.text[candidate.source_start : candidate.source_end]
                != candidate.source_text
            ):
                raise ValueError("unified Claim must quote exactly one target field")
        return candidates


def _assemble(resource, targets, contexts, bindings, package_hash, answer_keys=None, *, marker=None):
    marker = marker or MARKERS[resource.resource_type]
    parts, fields, offset = [], [], 0
    for field in targets:
        header = f"## {field.path} [{field.role}]\n\n"
        start = offset + len(header)
        parts.extend((header, field.text, "\n\n"))
        fields.append(
            dict(
                path=field.path,
                role=field.role,
                start=start,
                end=start + len(field.text),
            )
        )
        offset = start + len(field.text) + 2
    text = "".join(parts)
    snapshot = dict(
        version=VERSION,
        prompt_version=marker,
        resource_id=resource.resource_id,
        resource_version=resource.version,
        public_content_hash=content_digest(resource.content_text or ""),
        payload_hash=package_hash,
        audit_content_hash=content_digest(text),
        fields=fields,
        context_bindings=bindings,
        question_bindings=answer_keys or {},
        context_fields=[dict(path=f.path, role=f.role) for f in contexts],
    )
    return UnifiedSource(
        text,
        fields,
        snapshot,
        marker,
        [dict(path=f.path, role=f.role, text=f.text) for f in contexts],
    )


def _structured_questions(resource):
    from .resource_sources import (
        build_source as old_source,
        CHECKLIST_CONTEXT_PROMPT_VERSION,
        ASSESSMENT_PROMPT_VERSION,
    )

    assessment = resource.resource_type == "分阶测试题"
    old = old_source(
        resource,
        force=True,
        prompt_version=ASSESSMENT_PROMPT_VERSION
        if assessment
        else CHECKLIST_CONTEXT_PROMPT_VERSION,
    )
    if old.snapshot is None:
        # Old Markdown-only checklists have no private package to adapt.
        return None
    all_fields = [
        Field(f["path"], f["role"], old.text[f["start"] : f["end"]]) for f in old.fields
    ]
    selected = []
    for f in all_fields:
        if ".rubric[" in f.path:
            continue
        if assessment:
            keep = f.role in {"answer", "answer_option"}
        else:
            keep = f.role in {"answer", "answer_proposition", "explanation", "summary"}
        if keep:
            selected.append(f)
    contexts = [
        f
        for f in all_fields
        if ".rubric[" not in f.path and f.role not in {"criterion", "instruction"}
    ]
    original_fields = {f["path"]: f for f in old.fields}
    bindings = {}
    for field in selected:
        question = original_fields[field.path].get("question")
        bindings[field.path] = [
            f.path
            for f in contexts
            if question
            and original_fields[f.path].get("question") == question
            and f.path != field.path
        ]
    keys = {
        q: {k: v for k, v in value.items() if k != "question_text"}
        for q, value in old.snapshot["question_bindings"].items()
    }
    return _assemble(
        resource, selected, contexts, bindings, old.snapshot["payload_hash"], keys
    )


def _correction(resource):
    from .contextual_correction_sources import (
        build_source as old_source,
        _related_paths,
    )
    from app.core.learning_documents.correction_package import (
        correction_audit_source,
        validated_correction_package,
    )

    if resource.correction_package_payload is None:
        return None
    package = validated_correction_package(resource)
    if package.schema_version != "correction-package-v2":
        return None  # Historical V1 packages keep their compatible frozen source.
    old = old_source(resource)
    original = correction_audit_source(package)
    contexts = [
        Field(f.path, f.role, original.text[f.start : f.end]) for f in original.fields
    ]
    targets = [
        Field(f["path"], f["role"], old.text[f["start"] : f["end"]]) for f in old.fields
    ]
    available = {f.path for f in contexts}
    bindings = {}
    for f in targets:
        paths = _related_paths(f.path)
        if ".exercises." in f.path:
            base = f.path.rsplit(".", 1)[0]
            paths += [base + ".reference_answer", base + ".explanation"]
        bindings[f.path] = sorted({p for p in paths if p in available and p != f.path})
    return _assemble(resource, targets, contexts, bindings, package.payload_hash)


def _practice(resource, *, marker=UNIFIED_PRACTICE_SOURCE):
    from app.models.shared.agent_contracts import validate_practice_guide_package
    from app.agents.resource_agents.practice import (
        render_practice_guide_markdown,
        _canonical_hash,
    )

    package = resource.practice_guide_payload
    if package is None:
        return None  # A historical Markdown guide has no JSON fields to adapt.
    if not isinstance(package, dict):
        raise ValueError("practice Claim extraction requires a structured package")
    validated = validate_practice_guide_package(
        {k: v for k, v in package.items() if k != "payload_hash"}
    )
    if marker == UNIFIED_PRACTICE_SOURCE_V5 and validated.schema_version != "5.0":
        raise ValueError("practice V5 source requires a V5 package")
    package_hash = _canonical_hash(validated.model_dump(mode="json"))
    declared = getattr(resource, "practice_guide_payload_hash", None)
    if (
        package.get("payload_hash") != package_hash
        or (declared is not None and declared != package_hash)
        or (resource.content_text or "").strip()
        != render_practice_guide_markdown(package).strip()
    ):
        raise ValueError("practice extraction package/text identity mismatch")
    targets, contexts, bindings = [], [], {}

    def add(path, role, value, related=()):
        if not isinstance(value, str) or not value.strip():
            return
        targets.append(Field(path, role, value))
        contexts.append(Field(path, role, value))
        bindings[path] = list(related)

    concise_practice = marker in {UNIFIED_PRACTICE_SOURCE_V4, UNIFIED_PRACTICE_SOURCE_V5}
    contextual_scenario = marker in {UNIFIED_PRACTICE_SOURCE_V3, UNIFIED_PRACTICE_SOURCE_V4, UNIFIED_PRACTICE_SOURCE_V5}
    scenario_context = ["preparation.goal"] if contextual_scenario else []
    if concise_practice:
        contexts.append(Field("preparation.goal", "instruction", package["preparation"]["goal"]))
    else:
        add("preparation.goal", "instruction", package["preparation"]["goal"])
    for i, value in enumerate(package["preparation"]["items"]):
        add(f"preparation.items[{i}]", "instruction", value, ["preparation.goal"])
    material_paths = {}
    if marker == UNIFIED_PRACTICE_SOURCE_V5:
        for i, material in enumerate(package["preparation"].get("materials") or []):
            path = f"preparation.materials[{i}].content"
            contexts.append(Field(path, "question_context", material["content"]))
            material_paths[material["name"]] = path
    contexts.append(Field("practice.goal", "instruction", package["practice"]["goal"]))
    for i, step in enumerate(package["practice"]["steps"]):
        base = f"practice.steps[{i}]"
        contexts.append(Field(base + ".title", "label", step["title"]))
        related = scenario_context + ["practice.goal", base + ".title"]
        if marker == UNIFIED_PRACTICE_SOURCE_V5:
            related += [path for name, path in material_paths.items() if name in step["instruction_text"]]
        add(
            base + ".instruction_text", "instruction", step["instruction_text"], related
        )
        for j, code in enumerate(step["code_blocks"]):
            codepath = f"{base}.code_blocks[{j}]"
            add(
                codepath + ".purpose",
                "explanation",
                code["purpose"],
                related + [base + ".instruction_text"],
            )
            if marker in {UNIFIED_PRACTICE_SOURCE_V2, UNIFIED_PRACTICE_SOURCE_V3, UNIFIED_PRACTICE_SOURCE_V4, UNIFIED_PRACTICE_SOURCE_V5}:
                # Keep source code available for disambiguation without making
                # its local behavior an external-evidence Claim target.
                contexts.append(Field(codepath + ".code", "code", code["code"]))
                bindings[codepath + ".purpose"].append(codepath + ".code")
            else:
                add(
                    codepath + ".code",
                    "code",
                    code["code"],
                    related + [base + ".instruction_text", codepath + ".purpose"],
                )
        if concise_practice:
            contexts.append(Field(base + ".verification", "verification_requirement", step["verification"]))
        else:
            add(
                base + ".verification",
                "verification_requirement",
                step["verification"],
                related + [base + ".instruction_text"],
            )
    if concise_practice:
        contexts.append(Field("verification.goal", "instruction", package["verification"]["goal"]))
    else:
        add("verification.goal", "instruction", package["verification"]["goal"], scenario_context)
    for i, value in enumerate(package["verification"]["checklist"]):
        if concise_practice:
            contexts.append(Field(f"verification.checklist[{i}]", "verification_requirement", value))
        else:
            add(
                f"verification.checklist[{i}]",
                "verification_requirement",
                value,
                scenario_context + ["verification.goal"],
            )
    if concise_practice:
        contexts.append(Field("reflection.goal", "instruction", package["reflection"]["goal"]))
    else:
        add("reflection.goal", "instruction", package["reflection"]["goal"], scenario_context)
    add(
        "reflection.summary",
        "summary",
        package["reflection"]["summary"],
        scenario_context + ["reflection.goal"],
    )
    return _assemble(resource, targets, contexts, bindings, package_hash, marker=marker)


def build_source(resource, *, marker=None, input_version=None):
    expected = (
        UNIFIED_PRACTICE_SOURCE_V5
        if resource.resource_type == "实操指南" and input_version == "claim-input-context-v5" and (resource.practice_guide_payload or {}).get("schema_version") == "5.0"
        else UNIFIED_PRACTICE_SOURCE_V4
        if resource.resource_type == "实操指南" and input_version == "claim-input-context-v5"
        else UNIFIED_PRACTICE_SOURCE_V3
        if resource.resource_type == "实操指南" and input_version == "claim-input-context-v4"
        else UNIFIED_PRACTICE_SOURCE_V2
        if resource.resource_type == "实操指南" and input_version == "claim-input-context-v3"
        else MARKERS.get(resource.resource_type)
    )
    if marker in {UNIFIED_PRACTICE_SOURCE_V2, UNIFIED_PRACTICE_SOURCE_V3, UNIFIED_PRACTICE_SOURCE_V4, UNIFIED_PRACTICE_SOURCE_V5} and resource.resource_type == "实操指南":
        expected = marker
    if marker is not None and marker != expected:
        raise ValueError("unified extraction source marker mismatch")
    if resource.resource_type in {"分阶测试题", "复习清单"}:
        source = _structured_questions(resource)
    elif resource.resource_type == "个性化纠错训练包":
        source = _correction(resource)
    elif resource.resource_type == "实操指南":
        source = _practice(resource, marker=expected)
    else:
        source = None
    if source is None and marker is not None:
        raise ValueError("unified source marker requires its validated package")
    return source
