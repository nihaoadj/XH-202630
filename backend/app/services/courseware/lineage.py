"""Source-version reconciliation for published courseware."""

from collections.abc import Callable
from typing import Any

from app.services.learning_documents.resources import ResourceService


def reconcile_stale_resources(
    repo,
    resource_service: ResourceService,
    learner_id: str,
    emit_event: Callable[[str, str, str, dict[str, Any]], Any],
) -> None:
    latest_versions: dict[str, int] = {}
    for source in resource_service.list_by_learner(learner_id):
        family = source.resource_family_id or source.resource_id
        latest_versions[family] = max(latest_versions.get(family, 0), source.version)
    for resource in repo.list_resources(learner_id):
        if resource["status"] not in {"published", "stale"}:
            continue
        stale = any(
            latest_versions.get(item.get("resource_family_id") or item["resource_id"], item["version"])
            > item["version"]
            for item in resource.get("source_summary") or []
        )
        if stale and resource["status"] != "stale":
            repo.update_resource_status(resource["resource_id"], "stale")
            emit_event(resource["run_id"], "lineage", "stale", {"resource_id": resource["resource_id"]})
