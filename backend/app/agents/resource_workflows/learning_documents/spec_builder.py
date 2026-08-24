"""Deterministically freeze planner output into evidence-scoped resource specs."""

from __future__ import annotations

import uuid
from typing import Any, Iterable

from app.agents.resource_agents.registry import normalize_resource_type
from app.config import get_settings
from app.core.security.errors import ApplicationError, ErrorCode
from app.models.shared.agent_contracts import (
    ResourceRepresentationSpec,
    ResourceSpec,
)
from app.models.knowledge.knowledge import EvidenceItem


RESOURCE_SPEC_NAMESPACE = uuid.UUID("7fb4d9f0-5482-4cd4-bf19-d5556d751f49")


def _stable_uuid(run_id: str, resource_type: str, kind: str) -> str:
    return str(uuid.uuid5(RESOURCE_SPEC_NAMESPACE, f"{run_id}:{resource_type}:{kind}"))


def build_resource_specs(
    *,
    run_id: str,
    resource_types: Iterable[str],
    topic: str,
    difficulty: str,
    learning_plan: dict[str, Any],
    evidence: list[EvidenceItem],
    target_skill_nodes: list[str] | None = None,
) -> list[ResourceSpec]:
    if not evidence:
        raise ApplicationError(ErrorCode.EVIDENCE_INSUFFICIENT, status_code=422)
    normalized = [normalize_resource_type(item) for item in resource_types]
    if len(normalized) != len(set(normalized)):
        raise ApplicationError(ErrorCode.WORKFLOW_CONTRACT_INVALID, status_code=422)

    requirements = learning_plan.get("resource_requirements") or {}
    path_points = [
        str(item.get("topic")).strip()
        for item in learning_plan.get("learning_path", [])
        if isinstance(item, dict) and str(item.get("topic") or "").strip()
    ]
    knowledge_points = list(dict.fromkeys([*(target_skill_nodes or []), *path_points])) or [topic]
    evidence_ids = [item.evidence_id for item in evidence]
    settings = get_settings()
    specs: list[ResourceSpec] = []
    for order, resource_type in enumerate(normalized, start=1):
        objective = str(requirements.get(resource_type) or "").strip()
        if not objective:
            objective = f"完成本资源后能够围绕“{topic}”理解并应用核心知识。"
        representations = [
            ResourceRepresentationSpec(
                representation="text",
                max_output_tokens=settings.llm_resource_generator_max_output_tokens,
                display_order=1,
            )
        ]
        specs.append(ResourceSpec(
            resource_spec_id=_stable_uuid(run_id, resource_type, "spec"),
            resource_family_id=_stable_uuid(run_id, resource_type, "family"),
            resource_type=resource_type,
            learning_objective=objective,
            knowledge_points=knowledge_points,
            evidence_ids=evidence_ids,
            difficulty=difficulty,
            representations=representations,
            dependencies=[],
            display_order=order,
        ))
    return specs
