"""Unified revision guidance and payload assembly for resource generation (T46).

The six resource agents reuse the same two revision instructions. This module
only consumes the private revision-input models and the generation context; it
never imports services or the workflow, and it never performs construction or
database work.
"""

from __future__ import annotations

from typing import Any
from hashlib import sha256

from app.models.reviews.revision_inputs import (
    ClaimReviewRevisionInput,
    ResourceReviewRevisionInput,
)


ORDINARY_REVISION_GUIDANCE = (
    "这是一次普通审核返工：以上一版完整产物为底稿，逐条处理 "
    "resource_review_revision.issues 或 feedback.issues 指出的问题，逐条落实 "
    "feedback.revision_instructions（兼容审核反馈若存在）。按 issue_id、位置(location)、"
    "原要求(requirement)与验收条件(acceptance)定向修改，逐条核销并做全文回归；"
    "只修改被指出的问题，其余正确内容尽量原样保留。不得改写验收条件、补造证据外细节，"
    "也不得只用免责声明替代修正；证据不足时优先收缩或删除该陈述。若 unchanged 为 true，"
    "必须核对未满足条件与位置，不能只声称已修改。输出完整产物，沿用本类型原有输出格式。"
)

CLAIM_REVISION_GUIDANCE = (
    "这是一次 Claim 定向修订：以上一版完整产物（claim_review_revision.previous_text / "
    "previous_structured_payload）为底稿，按以下顺序处理："
    "1) 逐条读取 problems 的 claim_text，并通过 source_span_id 关联 spans 中的 source_text 定位原句；"
    "2) 依据 verdict 与 reason 做最小修正——contradicted 按 Judge 引用的冻结 evidence 修正"
    "或删除该事实，not_in_evidence 表示当前证据不支持，优先收缩或删除该陈述，不得补造支持事实；"
    "3) 只同步必要的关联内容（步骤、答案、解释、前后引用），其余正确内容尽量原样保留，"
    "不顺带润色、重排或扩写；"
    "4) 旧正文和审核理由都不是新事实证据，不得据此补造细节；"
    "5) 输出完整产物，沿用本类型原有输出格式。"
)

MINIMAL_CLAIM_REVISION_GUIDANCE = (
    "本次额外约束：只处理problems明确列出的矛盾和无证据断言，依据输入中已有的冻结evidence，"
    "优先改为有证据支持的表述；仍无支持时收缩或删除，不凭常识补事实，不把缺证等同事实为假。"
    "以previous_text为底稿，仅修改revision_edit_policy.target_ranges中的目标原句及必须同步的关联内容。"
    "groups.context_text只是阅读上下文，不代表整段均可改写。"
    "preserve_ranges中的非目标内容尽量逐字复制，保留标题、章节顺序、编号、Markdown格式、标点和空白；"
    "不顺带润色、换例子、重排段落或扩写。只有目标修改造成引用、答案或解释不一致时才做最小同步。"
    "输出前逐段对照旧正文检查，确认非目标部分保持一致，并输出完整产物。"
)


def _minimal_edit_policy(claim: ClaimReviewRevisionInput) -> dict[str, Any]:
    """Original-text coordinates guide copying without expanding edit scope."""
    text = claim.previous_text or ""
    def digest(value):
        return sha256(value.encode("utf-8")).hexdigest()
    if digest(text) != claim.content_hash:
        raise ValueError("revision preservation parent hash mismatch")
    target_span_ids = {problem.source_span_id for problem in claim.problems}
    intervals = []
    for span in claim.spans:
        if span.span_id not in target_span_ids:
            continue
        if (span.source_end > len(text)
                or text[span.source_start:span.source_end] != span.source_text
                or digest(span.source_text) != span.source_text_hash):
            raise ValueError("revision preservation span mismatch")
        intervals.append((span.source_start, span.source_end))
    merged: list[list[int]] = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    preserved = []
    cursor = 0
    for start, end in merged:
        if cursor < start:
            preserved.append((cursor, start))
        cursor = end
    if cursor < len(text):
        preserved.append((cursor, len(text)))
    return {
        "mode": "minimal_change_v1",
        "parent_content_hash": claim.content_hash,
        "coordinate_system": "previous_text Python character offsets; end exclusive",
        "target_ranges": [{"start": start, "end": end} for start, end in merged],
        "preserve_ranges": [{"start": start, "end": end, "sha256": digest(text[start:end])}
                            for start, end in preserved],
    }


def attach_revision_fields(payload: dict[str, Any], context) -> dict[str, Any]:
    """Attach the single active generation revision input to a prompt payload.

    At most one of ``claim_review_revision`` / ``resource_review_revision`` is
    non-null per resource context. When neither is present the payload is left
    unchanged so legacy callers keep their existing behaviour.
    """
    claim = getattr(context, "claim_review_revision", None)
    ordinary = getattr(context, "resource_review_revision", None)
    if claim is not None:
        payload["claim_review_revision"] = _dump(claim)
        payload["revision_guidance"] = CLAIM_REVISION_GUIDANCE
        if (getattr(context, "constraints", {}) or {}).get("_claim_revision_edit_policy") == "minimal_change_v1":
            payload["revision_edit_policy"] = _minimal_edit_policy(claim)
            payload["revision_guidance"] += MINIMAL_CLAIM_REVISION_GUIDANCE
    elif ordinary is not None:
        revision = _dump(ordinary)
        if ordinary.input_version == "2.0" and ordinary.previous_text is not None:
            from app.agents.resource_workflows.learning_documents.reviewing.resource_issues.adapters.base import paragraphs

            revision["previous_text"] = "\n".join(
                f"{line_id} | {line}" for line_id, line in paragraphs(ordinary.previous_text).items())
            payload["revision_guidance"] = (
                ORDINARY_REVISION_GUIDANCE
                + " 本次 previous_text 每行前的 p000001 等编号仅用于匹配旧版 issue.location 的"
                  " paragraph_id/end_paragraph_id，编号不是正文；输出完整新版时不得包含编号。"
                  " 旧版位置不可当作新版位置，跨行问题应处理起止行所覆盖的完整内容。"
            )
        else:
            payload["revision_guidance"] = ORDINARY_REVISION_GUIDANCE
        payload["resource_review_revision"] = revision
    return payload


def _dump(value: ResourceReviewRevisionInput | ClaimReviewRevisionInput) -> dict[str, Any]:
    return value.model_dump(mode="json")


__all__ = [
    "ORDINARY_REVISION_GUIDANCE",
    "CLAIM_REVISION_GUIDANCE",
    "attach_revision_fields",
]
