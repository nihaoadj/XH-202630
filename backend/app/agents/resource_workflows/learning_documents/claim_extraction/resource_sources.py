"""Versioned adapters for structured learning resources, not Judge contracts.

Audit text is a deterministic field-value document. Values are copied verbatim
from the persisted package; headings carry JSON paths, never generated facts.
Public Markdown and private assessment answers remain separate representations.
"""
from dataclasses import dataclass

from app.models.reviews.claim_extraction import content_digest, digest
from app.models.reviews.claims import (
    ClaimType, STRUCTURED_ASSESSMENT_SOURCE, STRUCTURED_CHECKLIST_SOURCE,
    CONTEXTUAL_CHECKLIST_SOURCE,
)

VERSION = "structured-learning-sources-v1"
ASSESSMENT_PROMPT_VERSION = STRUCTURED_ASSESSMENT_SOURCE
CHECKLIST_PROMPT_VERSION = STRUCTURED_CHECKLIST_SOURCE
CHECKLIST_CONTEXT_PROMPT_VERSION = CONTEXTUAL_CHECKLIST_SOURCE
CHECKLIST_GUIDANCE = """复习清单上下文规则 checklist-context-v2：
题干、待判断命题和候选例子是教学背景，不证明知识正确。答案键只标明作者的选择，不是Evidence。
answer_proposition 表示真假答案明确认可的原命题，须审核其中实际知识；保留假设、条件与否定，
不能把假设例子改成真实发生事件。错误命题、干扰项仍不是作者认可事实。
解释中的“与资料一致”“该项正确”“A为正例”等纯判题关系说明不单独作为factual；
同句若含具体技术知识，仍逐条抽取实际知识，不能整体略过解释。
例如“与教材一致，因为RAG在生成前检索外部知识”，只抽取其中具体技术断言。
claim_text须能独立读懂，可仅根据明确关联背景替换代词，保留主体、条件和否定；
source_text必须逐字来自当前目标字段的连续原文，不从只读背景另抽或拼接原文。
仅有“与资料一致”时不能借背景伪造一条技术事实；相关知识应从其自身审核目标抽取。
背景不足或用途冲突时返回uncertain，不输出指代不明的factual，也不能当作已通过。
"""
GUIDANCE = """本资源提供经过服务端校验的结构字段角色。只从 target_units 原文复制 source_text，
结构字段路径和角色仅用于消歧，不是事实证据，也不得从辅助上下文另抽候选。
exercise_proposition 是待学生判断的命题，exercise_option 是候选/干扰项，不代表作者认可，
标 non_factual。criterion/instruction 是教学达标要求，标 instructional；其中若另含独立事实，
事实仍须抽取。question_context 中的背景事实正常抽取，提问动作不算事实。
answer、answer_option、explanation、summary 中的实际事实必须抽取，不能整段略过。
答案键只是待审核的答案，不能证明其正确；answer_option 必须结合关联题干，特别注意
“错误的是/不正确的是”等否定提问，不把被选中的错误命题误写成作者认可的正面事实。
claim_text 可结合题意保留条件与否定，但 source_text 必须逐字来自当前目标原文；
不拼接原文，不改写引用，不补造事实。用途相冲突或无法消歧时返回 uncertain，不能假装通过。"""


def frozen_extension():
    return {**legacy_extension(), "checklist_context": {
        "version": CHECKLIST_CONTEXT_PROMPT_VERSION, "guidance_hash": digest(CHECKLIST_GUIDANCE)}}


def legacy_extension():
    return {"version": VERSION, "guidance_hash": digest(GUIDANCE)}


def enabled(policy):
    extension = getattr(policy, "structured_sources", None)
    if extension is None:
        return False
    if extension not in (legacy_extension(), frozen_extension()):
        raise ValueError("structured source adapter contract drift")
    return True


@dataclass(frozen=True)
class AuditSource:
    text: str
    fields: list[dict]
    snapshot: dict | None
    prompt_version: str | None = None
    related_fields: list[dict] | None = None

    def classify(self, candidates):
        result = []
        for candidate in candidates:
            matches = [f for f in self.fields if f["start"] <= candidate.source_start
                       and candidate.source_end <= f["end"]]
            if self.prompt_version == CHECKLIST_CONTEXT_PROMPT_VERSION and len(matches) != 1:
                raise ValueError("checklist Claim must quote exactly one target field")
            if not matches:
                # Metadata headings must not become facts. Cross-field copies
                # are rejected instead of allowing a Claim to adopt two roles.
                if candidate.claim_type == ClaimType.FACTUAL:
                    raise ValueError("structured Claim has no unique field source")
            elif len(matches) != 1:
                raise ValueError("ambiguous structured Claim source")
            else:
                role = matches[0]["role"]
                if role in {"exercise_proposition", "exercise_option"}:
                    candidate = candidate.model_copy(update={"claim_type": ClaimType.NON_FACTUAL})
                elif role in {"criterion", "instruction"} and (
                    candidate.source_start == matches[0]["start"] and candidate.source_end == matches[0]["end"]
                ):
                    # The full teaching requirement is an instruction. A
                    # separately located factual clause inside it stays factual.
                    candidate = candidate.model_copy(update={"claim_type": ClaimType.INSTRUCTIONAL})
            result.append(candidate)
        return result


def build_source(resource, policy=None, *, force=False, prompt_version=None):
    if not force and policy is not None:
        from .input_context import enabled as unified_enabled
        if unified_enabled(policy):
            from .unified_sources import build_source as unified_source
            source = unified_source(resource, input_version=policy.input_contract["version"])
            if source is not None:
                return source
    kind = resource.resource_type
    if kind == "个性化纠错训练包" and resource.correction_package_payload is not None:
        from .correction_sources import build_source as correction_source
        return correction_source(resource, policy, force=force)
    if kind not in {"复习清单", "分阶测试题"}:
        return AuditSource(resource.content_text or "", [], None)
    if not force and (policy is None or not enabled(policy)):
        return AuditSource(resource.content_text or "", [], None)
    if force and prompt_version not in {None, ASSESSMENT_PROMPT_VERSION,
                                       CHECKLIST_PROMPT_VERSION, CHECKLIST_CONTEXT_PROMPT_VERSION}:
        raise ValueError("unknown structured Claim source version")
    contextual = kind == "复习清单" and (
        prompt_version == CHECKLIST_CONTEXT_PROMPT_VERSION or
        (prompt_version is None and (force or getattr(policy, "structured_sources", None) == frozen_extension())))
    package = getattr(resource, "assessment_payload" if kind == "分阶测试题" else "review_practice_payload", None)
    if package is None:
        if kind == "分阶测试题":
            raise ValueError("assessment Claim audit requires a private structured package")
        return AuditSource(resource.content_text or "", [], None)
    if not isinstance(package, dict):
        raise ValueError("structured Claim package invalid")
    from app.agents.resource_agents.checklist import render_review_practice_markdown
    from app.agents.resource_agents.assessment import render_assessment_markdown
    from app.models.shared.agent_contracts import ReviewPracticePackageV2, AssessmentPackageV2
    (AssessmentPackageV2 if kind == "分阶测试题" else ReviewPracticePackageV2).model_validate(
        {k: v for k, v in package.items() if k != "payload_hash"})
    from hashlib import sha256
    import json
    values = {k: v for k, v in package.items() if k != "payload_hash"}
    package_hash = sha256(json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if package.get("payload_hash") != package_hash:
        raise ValueError("structured Claim package hash mismatch")
    declared_hash = getattr(resource, "assessment_payload_hash" if kind == "分阶测试题" else "review_practice_payload_hash", None)
    if declared_hash is not None and declared_hash != package_hash:
        raise ValueError("structured Claim persisted package hash mismatch")
    original = resource.content_text or ""
    rendered = (render_assessment_markdown if kind == "分阶测试题" else render_review_practice_markdown)(package)
    legacy = rendered.replace("请结合关联材料核对。", "已完成来源核验。")
    # Old checklist notices were prefixed 小结依据/证据依据, preserved by renderer.
    # LearningResource strips surrounding whitespace on persisted text fields.
    if original not in {rendered, legacy, rendered.strip(), legacy.strip()}:
        raise ValueError("structured Claim package/Markdown mismatch")
    parts, fields, bindings, offset = [], [], {}, 0
    def add(path, role, value, question=None):
        nonlocal offset
        if not isinstance(value, str) or not value.strip():
            return
        header = f"## {path} [{role}]\n\n"
        parts.extend([header, value, "\n\n"])
        start = offset + len(header)
        fields.append({"path": path, "role": role, "start": start, "end": start + len(value),
                       **({"question": question} if question else {})})
        offset = start + len(value) + 2
    add("instructions", "instruction", package.get("instructions"))
    for b, block in enumerate(package["node_blocks"]):
        base = f"node_blocks[{b}]"
        if kind == "分阶测试题":
            for group in ("single_choice_questions", "multiple_choice_questions", "short_answer_questions"):
                for n, q in enumerate(block[group]):
                    path = f"{base}.{group}[{n}]"
                    bindings[path] = {"question_text": q["stem"], "answer_option_ids": q.get("answer_option_ids", [])}
                    add(path + ".stem", "question_context", q["stem"], path)
                    for i, option in enumerate(q.get("options", [])):
                        role = "answer_option" if option["option_id"] in q["answer_option_ids"] else "exercise_option"
                        add(f"{path}.options[{i}].text", role, option["text"], path)
                    add(path + ".reference_answer", "answer", q.get("reference_answer"), path)
                    add(path + ".explanation", "explanation", q.get("explanation"), path)
                    for i, item in enumerate(q.get("rubric", [])):
                        add(f"{path}.rubric[{i}].criterion", "answer", item["criterion"], path)
        else:
            for group in ("recall_questions", "distinction_questions", "example_recognition_questions", "example_recognition"):
                items = block.get(group) or []
                if isinstance(items, dict):
                    items = [items]
                for n, q in enumerate(items):
                    path = f"{base}.{group}[{n}]"
                    bindings[path] = {k: q[k] for k in ("truth_value", "positive_candidate") if k in q}
                    for key, role in (("prompt", "question_context"), ("statement", "exercise_proposition"),
                                      ("candidate_a", "exercise_option"), ("candidate_b", "exercise_option"),
                                      ("reference_answer", "answer"), ("correction", "answer"),
                                      ("decisive_boundary", "answer"), ("explanation", "explanation"),
                                      ("pass_criteria", "criterion")):
                        if contextual and key == "statement" and q.get("truth_value") is True:
                            role = "answer_proposition"
                        add(path + "." + key, role, q.get(key), path)
            add(base + ".knowledge_summary", "summary", block["knowledge_summary"])
    audit_text = "".join(parts)
    prompt_version = (ASSESSMENT_PROMPT_VERSION if kind == "分阶测试题" else
                      CHECKLIST_CONTEXT_PROMPT_VERSION if contextual else CHECKLIST_PROMPT_VERSION)
    snapshot = {"version": VERSION, "prompt_version": prompt_version, "resource_id": resource.resource_id, "resource_version": resource.version,
                "public_content_hash": content_digest(original), "payload_hash": package_hash,
                "audit_content_hash": content_digest(audit_text), "fields": fields, "question_bindings": bindings}
    return AuditSource(audit_text, fields, snapshot, prompt_version)


def source_for_claims(resource, claims):
    """Rebuild the exact private source only for explicitly marked new Claims."""
    markers = {c.extractor_prompt_version for c in claims}
    from .unified_sources import MARKERS, build_source as unified_source
    from app.models.reviews.claims import UNIFIED_SOURCE_MARKERS
    if markers & UNIFIED_SOURCE_MARKERS:
        if len(markers) != 1:
            raise ValueError("mixed unified Claim source versions")
        return unified_source(resource, marker=next(iter(markers)))
    from .correction_sources import PROMPT_VERSION as correction_marker, build_source as correction_source
    from .filtered_correction_sources import PROMPT_VERSION as filtered_marker
    from .compact_correction_sources import PROMPT_VERSION as compact_marker
    from .contextual_correction_sources import PROMPT_VERSION as contextual_marker
    if markers & {correction_marker, filtered_marker, compact_marker, contextual_marker}:
        if len(markers) != 1:
            raise ValueError("mixed correction Claim source versions")
        return correction_source(resource, force=True, prompt_version=next(iter(markers)))
    if resource.correction_package_payload is not None:
        raise ValueError("structured correction Claims missing source identity")
    if markers & {ASSESSMENT_PROMPT_VERSION, CHECKLIST_PROMPT_VERSION, CHECKLIST_CONTEXT_PROMPT_VERSION}:
        if len(markers) != 1:
            raise ValueError("mixed structured Claim source versions")
        source = build_source(resource, force=True, prompt_version=next(iter(markers)))
        if source.prompt_version is None or markers != {source.prompt_version}:
            raise ValueError("mixed structured Claim source versions")
        return source
    if any(marker.startswith("structured-checklist-") for marker in markers):
        raise ValueError("unknown checklist Claim source version")
    if any(marker.startswith(("structured-assessment-", "structured-correction-",
                              "structured-practice-")) for marker in markers):
        raise ValueError("unknown structured Claim source version")
    return AuditSource(resource.content_text or "", [], None)
