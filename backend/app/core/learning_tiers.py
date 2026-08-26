"""Deterministic three-tier learning policy shared by all learning domains."""

from __future__ import annotations

from collections.abc import Iterable


TIER_POLICY_VERSION = "learner-levels/v1"
MIN_TIER = 1
MAX_TIER = 3

TIER_LABELS = {1: "零基础", 2: "Python 基础", 3: "进阶 RAG"}
TIER_DIFFICULTIES = {1: "初级", 2: "中级", 3: "高级"}
_LEVEL_ALIASES = {
    "初级": 1, "零基础": 1, "L1": 1,
    "中级": 2, "Python 基础": 2, "L2": 2,
    "进阶": 3, "高级": 3, "进阶 RAG": 3, "L3": 3,
}


def tier_for_level(value: str | None) -> int:
    """Map every accepted legacy label to its ordered tier or fail closed."""
    try:
        return _LEVEL_ALIASES[str(value).strip()]
    except (KeyError, AttributeError):
        raise ValueError(f"unknown learning tier label: {value!r}") from None


def label_for_tier(tier: int) -> str:
    if tier not in TIER_LABELS:
        raise ValueError(f"invalid learning tier: {tier!r}")
    return TIER_LABELS[tier]


def difficulty_for_tier(tier: int) -> str:
    if tier not in TIER_DIFFICULTIES:
        raise ValueError(f"invalid learning tier: {tier!r}")
    return TIER_DIFFICULTIES[tier]


def validate_tier_graph(nodes: Iterable[object]) -> None:
    """Reject a graph whose prerequisite points from a higher tier to a lower one."""
    node_list = list(nodes)
    tiers = {str(node.node_id): int(node.tier) for node in node_list}
    for node in node_list:
        for prerequisite in getattr(node, "prerequisites", []):
            parent_tier = tiers.get(str(prerequisite))
            if parent_tier is not None and parent_tier > int(node.tier):
                raise ValueError("a prerequisite cannot have a higher tier than its child")


__all__ = [
    "TIER_POLICY_VERSION", "MIN_TIER", "MAX_TIER", "TIER_LABELS", "TIER_DIFFICULTIES",
    "tier_for_level", "label_for_tier", "difficulty_for_tier", "validate_tier_graph",
]
