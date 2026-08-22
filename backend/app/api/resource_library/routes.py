"""Read-only aggregate projection for text resources and courseware."""

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.models.resource_library import ResourceLibraryItem


router = APIRouter()


@router.get("/{learner_id}", response_model=list[ResourceLibraryItem])
def list_resource_library(learner_id: str, request: Request):
    profile = request.app.container.profile_service().get(learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    text_items = [
        ResourceLibraryItem(
            id=item.resource_id, resource_kind="text", title=item.resource_type,
            topic=item.topic, learner_id=learner_id, created_at=item.created_at,
            published_at=item.published_at, version=item.version, status=item.publication_status,
            preview_capability=True, download_capability=bool(item.file_path), run_id=item.run_id,
            batch_id=item.batch_id, resource_type=item.resource_type, difficulty=item.difficulty,
            knowledge_points=item.knowledge_points,
        )
        for item in request.app.container.resource_service().list_by_learner(learner_id)
    ]
    courseware_items = request.app.container.courseware_service().list_library_items(learner_id)
    # Legacy resources may not have persisted timestamps.  Sort deterministically
    # without allowing one incomplete historical row to break the whole library.
    return sorted(
        text_items + courseware_items,
        key=lambda item: str(item.published_at or item.created_at or ""),
        reverse=True,
    )
