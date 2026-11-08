"""Unified revision guidance and payload assembly for resource generation (T46).

The six resource agents reuse the same two revision instructions. This module
only consumes the private revision-input models and the generation context; it
never imports services or the workflow, and it never performs construction or
database work.
"""

from __future__ import annotations

from typing import Any

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
    elif ordinary is not None:
        payload["resource_review_revision"] = _dump(ordinary)
        payload["revision_guidance"] = ORDINARY_REVISION_GUIDANCE
    return payload


def _dump(value: ResourceReviewRevisionInput | ClaimReviewRevisionInput) -> dict[str, Any]:
    return value.model_dump(mode="json")


__all__ = [
    "ORDINARY_REVISION_GUIDANCE",
    "CLAIM_REVISION_GUIDANCE",
    "attach_revision_fields",
]
