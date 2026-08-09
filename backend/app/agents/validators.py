"""Pure validators for P0-05 review instructions and resource lineage."""

from __future__ import annotations

from typing import Any, Iterable

from app.models.schemas import LearningResource


KNOWN_ISSUE_CODES = frozenset(
    {
        "factual_risk",
        "evidence_gap",
        "procedure_error",
        "difficulty_mismatch",
        "coverage_gap",
        "structure_quality",
        "other",
    }
)


def revision_instructions_are_valid(
    instructions: Iterable[dict[str, Any]],
    resource_types: Iterable[str],
) -> bool:
    allowed_types = set(resource_types)
    saw_instruction = False
    for item in instructions:
        saw_instruction = True
        if not isinstance(item, dict):
            return False
        codes = item.get("issue_codes")
        if not isinstance(codes, list) or not codes or any(code not in KNOWN_ISSUE_CODES for code in codes):
            return False
        if item.get("target_resource_type") not in allowed_types:
            return False
        if not isinstance(item.get("action"), str) or not item["action"].strip():
            return False
        priority = item.get("priority", 1)
        if not isinstance(priority, int) or isinstance(priority, bool) or priority < 1:
            return False
    return saw_instruction


def validate_resource_lineage(
    resource: LearningResource,
    previous: LearningResource | None,
) -> None:
    if resource.version < 1:
        raise ValueError("resource version must be positive")
    if previous is None:
        if resource.version != 1 or resource.parent_resource_id is not None:
            raise ValueError("first resource version must be v1 without parent")
        return
    if resource.resource_id == previous.resource_id:
        raise ValueError("a revision must use a new resource_id")
    if resource.resource_type != previous.resource_type:
        raise ValueError("resource lineage cannot change resource_type")
    if resource.version != previous.version + 1:
        raise ValueError("resource version must increment by one")
    if resource.parent_resource_id != previous.resource_id:
        raise ValueError("resource parent must reference the previous version")


def immutable_resource_payload(resource: LearningResource) -> dict[str, Any]:
    return resource.model_dump(
        mode="json",
        include={
            "resource_id",
            "learner_id",
            "topic",
            "resource_type",
            "difficulty",
            "storage_type",
            "content_text",
            "knowledge_points",
            "source_refs",
            "learning_path_node",
            "version",
            "parent_resource_id",
            "exercise_items",
        },
    )
