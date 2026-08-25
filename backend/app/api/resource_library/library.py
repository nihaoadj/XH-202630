"""Read-only aggregate projection for text resources and courseware."""

from fastapi import APIRouter, HTTPException, Request

from app.api.dependencies import ensure_profile_access
from app.models.shared.resource_library import ResourceLibraryItem


router = APIRouter()


@router.get("/{learner_id}", response_model=list[ResourceLibraryItem])
def list_resource_library(learner_id: str, request: Request):
    profile = request.app.container.profile_service().get(learner_id)
    if ensure_profile_access(request, profile) is None:
        raise HTTPException(status_code=404, detail="学习者画像不存在")
    library_provider = getattr(request.app.container, "resource_library_service", None)
    if library_provider is not None:
        return library_provider().list_by_learner(learner_id)

    # Keep lightweight test containers and older embedding applications
    # functional while the production container uses the domain service.
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
    courseware_provider = getattr(request.app.container, "courseware_service", None)
    courseware_items = (
        courseware_provider().list_library_items(learner_id)
        if courseware_provider is not None
        else []
    )
    return sorted(text_items + courseware_items,
                  key=lambda item: str(item.published_at or item.created_at or ""),
                  reverse=True)
