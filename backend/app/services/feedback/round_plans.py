"""Pure single-node production plans; no database, dispatch or model calls."""

from dataclasses import dataclass
from typing import Literal

from app.core.learning_tiers import difficulty_for_tier
from app.models.learning_documents.schemas import GenerateRequest, SkillNode
from app.models.learning_documents.types import GENERAL_GENERATION_RESOURCE_TYPES
from app.models.shared.persistence import canonical_hash

REVIEW_RESOURCES = ("复习清单", "分阶测试题")
CORRECTION_RESOURCES = ("个性化纠错训练包", "分阶测试题")


def round_identity(prefix: str, *parts: object) -> str:
    return prefix + "_" + canonical_hash(parts)[:48]


@dataclass(frozen=True)
class RoundMemberPlan:
    member_id: str
    node_id: str
    name: str
    tier: int
    role: Literal["primary", "review", "legacy"]
    stage_node_id: str
    batch_id: str
    difficulty: str
    resource_types: tuple[str, ...]
    requests: tuple[GenerateRequest, ...]


def plan_member(
    *, round_id: str, stage_id: str, learner_id: str, knowledge_base_id: str,
    node: SkillNode, role: Literal["primary", "review", "legacy"],
    primary_resource_types: list[str], include_claim_check: bool,
    correction_focus: dict | None = None,
) -> RoundMemberPlan:
    """A node's role/stage determines its resources before any job is created."""
    if node.knowledge_base_id != knowledge_base_id or node.tier not in {1, 2, 3}:
        raise ValueError("node must have a known tier in the selected knowledge base")
    correction = correction_focus is not None
    if role == "legacy" and not correction:
        raise ValueError("legacy imports do not produce initial resources")
    if role not in {"primary", "review", "legacy"}:
        raise ValueError("unknown round role")
    if correction:
        resource_types = CORRECTION_RESOURCES
    elif role == "review":
        resource_types = REVIEW_RESOURCES
    else:
        resource_types = tuple(dict.fromkeys(primary_resource_types))
        if not resource_types or not set(resource_types) <= set(GENERAL_GENERATION_RESOURCE_TYPES):
            raise ValueError("primary resource types must be general learning resources")
    member_id = round_identity("rn", round_id, role, node.node_id)
    stage_node_id = round_identity("sn", stage_id, member_id)
    batch_id = round_identity("batch", stage_node_id)
    difficulty = difficulty_for_tier(node.tier)
    constraints = {
        "target_tier": node.tier,
        **({"correction_focus_snapshot": correction_focus, "selection_type": "correction_package"}
           if correction else {}),
    }
    groups = tuple((resource_type,) for resource_type in resource_types) if include_claim_check else (resource_types,)
    requests = tuple(GenerateRequest(
        learner_id=learner_id, knowledge_base_id=knowledge_base_id, topic=node.name,
        target_skill_nodes=[node.node_id], profile_focus_mode="off", resource_types=list(group),
        difficulty_preference=difficulty, include_claim_check=include_claim_check,
        include_review=True, generation_mode="standard", max_iterations=2, constraints=constraints,
    ) for group in groups)
    return RoundMemberPlan(member_id, node.node_id, node.name, node.tier, role,
                           stage_node_id, batch_id, difficulty, resource_types, requests)
