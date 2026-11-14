"""Immutable resource projections shared by persistence and workflow validation."""

from typing import Any

from app.models.learning_documents.schemas import LearningResource


def immutable_resource_payload(resource: LearningResource) -> dict[str, Any]:
    result = resource.model_dump(
        mode="json",
        include={
            "resource_id",
            "learner_id",
            "topic",
            "resource_type",
            "resource_spec_id",
            "resource_family_id",
            "representation",
            "difficulty",
            "storage_type",
            "content_text",
            "knowledge_points",
            "source_refs",
            "learning_path_node",
            "version",
            "parent_resource_id",
            "exercise_items",
            "assessment_payload",
            "assessment_payload_hash",
        },
    )

    if resource.correction_package_payload is not None:
        result["correction_package_payload"] = resource.correction_package_payload
        result["correction_package_payload_hash"] = resource.correction_package_payload_hash
    return result
