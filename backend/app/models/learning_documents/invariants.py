"""Immutable resource projections shared by persistence and workflow validation."""

from typing import Any

from app.models.learning_documents.schemas import LearningResource


def immutable_resource_payload(resource: LearningResource) -> dict[str, Any]:
    return resource.model_dump(
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
