"""Read-only aggregation across text resources and interactive courseware."""

from __future__ import annotations

import logging

from app.models.shared.resource_library import ResourceLibraryItem


logger = logging.getLogger(__name__)


class ResourceLibraryService:
    """Own the cross-domain projection without owning generation logic."""

    def __init__(self, resource_service, courseware_service):
        self.resource_service = resource_service
        self.courseware_service = courseware_service

    def list_by_learner(self, learner_id: str) -> list[ResourceLibraryItem]:
        text_items = [
            ResourceLibraryItem(
                id=item.resource_id,
                resource_kind="text",
                title=item.resource_type,
                topic=item.topic,
                learner_id=learner_id,
                created_at=item.created_at,
                published_at=item.published_at,
                version=item.version,
                status=item.publication_status,
                preview_capability=True,
                download_capability=bool(item.file_path),
                run_id=item.run_id,
                batch_id=item.batch_id,
                resource_type=item.resource_type,
                difficulty=item.difficulty,
                knowledge_points=item.knowledge_points,
            )
            for item in self.resource_service.list_by_learner(learner_id)
        ]
        # Interactive courseware is an optional projection in this read model.
        # A stale/missing courseware table or malformed legacy row must not
        # make the text-resource page unusable.
        try:
            courseware_items = self.courseware_service.list_library_items(learner_id)
        except Exception:  # pragma: no cover - concrete storage errors vary by backend
            logger.exception("courseware library projection unavailable")
            courseware_items = []
        return sorted(
            text_items + courseware_items,
            key=lambda item: str(item.published_at or item.created_at or ""),
            reverse=True,
        )


__all__ = ["ResourceLibraryService"]
