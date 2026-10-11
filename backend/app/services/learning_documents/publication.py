"""Claim publication use case; preserve resource commit before audit append."""

from __future__ import annotations

from collections.abc import Callable
import hashlib
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from app.config import Settings
from app.db.audit.base import BaseAuditRepository
from app.models.learning_documents.schemas import LearningResource
from app.models.shared.persistence import WorkflowEventType

if TYPE_CHECKING:
    from app.services.learning_documents.resources import ResourceService
    from app.services.runs.queries import RunQueryService


class ResourcePublicationConflict(ValueError):
    """The resource cannot accept the requested publication decision."""


def decide_claim_publication(
    service: ResourceService,
    resource: LearningResource,
    *,
    resource_id: str,
    publish: bool,
    settings_factory: Callable[[], Settings],
    run_query_factory: Callable[[], RunQueryService],
    audit_factory: Callable[[], BaseAuditRepository],
) -> LearningResource | None:
    """Check the existing Claim gates, persist the decision, then append its event."""
    if not resource.claim_publish_decision_pending:
        if resource.claim_publish_decision == ("published_by_user" if publish else "rejected_by_user"):
            _record_publication_event(resource, audit_factory, replay=True)
            return resource
        raise ResourcePublicationConflict("该资源当前不处于待用户决策状态")
    if resource.claim_metric_status != "complete":
        raise ResourcePublicationConflict("Claim 审核尚未完成")
    if (resource.claim_factual_pass_rate is None or resource.claim_factual_pass_rate < settings_factory().claim_user_review_min_factual_pass_rate):
        raise ResourcePublicationConflict("事实 Claim 通过率未达到用户决策阈值")
    claims_response = run_query_factory().get_claims(resource.run_id or "")
    metric = claims_response.resource_metrics.get(resource_id)
    if metric is None or metric.contradicted_claim_total > 0:
        raise ResourcePublicationConflict("存在矛盾事实 Claim，禁止发布")
    updated = service.update_publication_decision(resource_id, publish=publish)
    if updated is not None:
        _record_publication_event(updated, audit_factory)
    return updated


def _record_publication_event(
    resource: LearningResource,
    audit_factory: Callable[[], BaseAuditRepository],
    *,
    replay: bool = False,
) -> None:
    """Replay a decision without duplicating either new or legacy audit events."""
    if not resource.run_id:
        return
    audit = audit_factory()
    payload = {
        "resource_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "publication_status": resource.publication_status,
        "claim_publish_decision": resource.claim_publish_decision,
    }
    if replay and callable(getattr(audit, "list_events", None)):
        after_sequence = 0
        while events := audit.list_events(resource.run_id, after_sequence=after_sequence, limit=100):
            if any(
                event.event_type == WorkflowEventType.RESOURCE_PUBLICATION_DECIDED
                and event.payload == payload and event.status == resource.publication_status
                for event in events
            ):
                return
            after_sequence = events[-1].event_sequence
    identity = "\x1f".join((resource.run_id, resource.resource_id, resource.claim_publish_decision))
    audit.append_event(
        resource.run_id,
        WorkflowEventType.RESOURCE_PUBLICATION_DECIDED,
        payload=payload,
        occurred_at=datetime.now(timezone.utc),
        status=resource.publication_status,
        event_id=f"evt_{hashlib.sha256(identity.encode()).hexdigest()[:32]}",
    )
