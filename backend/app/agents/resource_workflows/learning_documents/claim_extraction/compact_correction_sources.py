"""V3 correction source: display fields stay visible, outside Claim targets."""

from .filtered_correction_sources import (
    GUIDANCE as FILTERED_GUIDANCE, EXCLUDED_LEAF_KEYS, build_source as filtered_source,
)
from app.models.reviews.claim_extraction import digest
from app.models.reviews.claims import COMPACT_CORRECTION_SOURCE

VERSION = "correction-content-sources-v3"
PROMPT_VERSION = COMPACT_CORRECTION_SOURCE
DISPLAY_ROOTS = ("content.training_goals", "content.focus_overview",
                 "content.mastery_criteria", "content.next_review_actions")
GUIDANCE = FILTERED_GUIDANCE + """
来源correction-content-sources-v3额外排除训练目标、薄弱概览、达标标准及后续复习动作。
这些展示字段不作为抽取目标，也不得从上下文补抽；目标节点、学习状态、失分维度由服务端控制，不抽事实。
剩余解释、概念补救、正确陈述、两组练习的答案/解析/提示、反馈和总结中的技术结论正常核验。
"""


def frozen_extension():
    return {"version": VERSION, "guidance_hash": digest(GUIDANCE),
            "field_policy_hash": digest({"excluded_leaf_keys": sorted(EXCLUDED_LEAF_KEYS),
                                       "excluded_roots": list(DISPLAY_ROOTS),
                                       "context_policy": "related-correction-fields-v1"})}


def build_source(resource):
    return filtered_source(resource, version=VERSION, prompt_version=PROMPT_VERSION, excluded_roots=DISPLAY_ROOTS)
