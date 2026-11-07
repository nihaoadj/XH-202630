"""Read-only publication facts for one generation run.

The aggregate answers "how many logical resources of this run have a readable
published body right now".  It uses only the frozen request specification,
execution projections and persisted resource versions; it never recomputes a
publication permission, writes state, appends events or calls a model.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from app.db.learning_documents.base import BaseResourceRepository
from app.db.learning_documents.models import ResourceExecutionRecord, ResourceSpecRecord
from app.models.generation.progress import (
    PublishCompleteness,
    PublishIncompleteReason,
    RunPublishSummary,
)
from app.models.learning_documents.schemas import LearningResource
from app.models.learning_documents.types import canonical_resource_type

CANONICAL_TEXT = "text"

_REASON_ORDER = {reason: index for index, reason in enumerate(PublishIncompleteReason)}


@dataclass
class _Slot:
    """One logical resource of the run: published at most once."""

    key: str
    in_denominator: bool
    published: bool = False
    pending: bool = False


def _canonical_type(value: object) -> str | None:
    try:
        return canonical_resource_type(str(value or ""))
    except ValueError:
        return None


def _resolve_slot_key(
    resource: LearningResource,
    *,
    family_to_spec: Mapping[str, str],
    resources_by_id: Mapping[str, LearningResource],
) -> tuple[str | None, bool]:
    """Return ``(slot_key, lineage_conflict)`` for one resource version.

    Identity prefers the explicit spec, then a trusted family relation, then a
    same-run parent chain.  A cycle, a dangling parent or an unsupported
    relation is reported as a conflict instead of being merged by resource type.
    """

    if resource.resource_spec_id:
        return resource.resource_spec_id, False
    seen: set[str] = set()
    current: LearningResource | None = resource
    while current is not None:
        if current.resource_id in seen:
            return None, True
        seen.add(current.resource_id)
        family = current.resource_family_id
        if family and family in family_to_spec:
            return family_to_spec[family], False
        if current.resource_spec_id:
            return current.resource_spec_id, False
        parent_id = current.parent_resource_id
        if not parent_id:
            return None, False
        parent = resources_by_id.get(parent_id)
        if parent is None:
            return None, True
        current = parent
    return None, False


def _readable_published_resource(
    candidates: Sequence[LearningResource],
    preferred_id: str | None,
) -> LearningResource | None:
    """Pick the exact version a reader should open for this slot."""

    published = [item for item in candidates if item.publication_status == "published"]
    if not published:
        return None
    if preferred_id:
        for item in published:
            if item.resource_id == preferred_id:
                return item
    return sorted(published, key=lambda item: (-int(item.version or 0), item.resource_id))[0]


def aggregate_publication_summary(
    *,
    run_id: str,
    request_payload: Mapping[str, object] | None,
    specs: Sequence[ResourceSpecRecord] | None,
    executions: Sequence[ResourceExecutionRecord] | None,
    resources: Sequence[LearningResource] | None,
) -> RunPublishSummary:
    """Aggregate publication facts from a complete in-memory run snapshot.

    ``None`` means the caller could not load that collection, which is a
    capability gap; an empty sequence means it was loaded and is genuinely
    empty.  The two are never conflated.
    """

    if specs is None or executions is None or resources is None:
        return RunPublishSummary(
            completeness=PublishCompleteness.UNAVAILABLE,
            incomplete_reasons=[PublishIncompleteReason.REPOSITORY_UNAVAILABLE],
        )

    reasons: dict[PublishIncompleteReason, None] = {}

    def flag(reason: PublishIncompleteReason) -> None:
        reasons.setdefault(reason, None)

    run_specs = [spec for spec in specs if spec.run_id == run_id]
    run_resources = [
        resource for resource in resources if resource.run_id in (None, run_id)
    ]
    run_executions = [
        execution for execution in executions if execution.run_id == run_id
    ]

    request_types: list[str] | None = None
    if isinstance(request_payload, Mapping):
        raw_types = request_payload.get("resource_types")
        if isinstance(raw_types, (list, tuple)) and raw_types:
            resolved: list[str] = []
            for raw in raw_types:
                canonical = _canonical_type(raw) if isinstance(raw, str) else None
                if canonical is None:
                    flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)
                    continue
                if canonical not in resolved:
                    resolved.append(canonical)
            request_types = resolved or None

    slots: dict[str, _Slot] = {}
    specs_by_type: dict[str, list[str]] = {}
    family_to_spec: dict[str, str] = {}
    for spec in sorted(run_specs, key=lambda item: (item.display_order, item.resource_spec_id)):
        slots[spec.resource_spec_id] = _Slot(key=spec.resource_spec_id, in_denominator=True)
        canonical = _canonical_type(spec.resource_type)
        if canonical is None:
            flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)
        else:
            specs_by_type.setdefault(canonical, []).append(spec.resource_spec_id)
        if spec.resource_family_id:
            family_to_spec.setdefault(spec.resource_family_id, spec.resource_spec_id)
    for spec_ids in specs_by_type.values():
        if len(spec_ids) > 1:
            # The current contract maps one resource type to one spec per run;
            # anything else means the request scope cannot be reconstructed.
            flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)

    if request_types is None:
        flag(PublishIncompleteReason.REQUEST_MISSING)
    else:
        for canonical in request_types:
            if canonical not in specs_by_type:
                slot_key = f"request:{canonical}"
                slots.setdefault(slot_key, _Slot(key=slot_key, in_denominator=True))
                flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)
        for canonical in specs_by_type:
            if canonical not in request_types:
                flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)

    resources_by_id = {resource.resource_id: resource for resource in run_resources}
    slot_resources: dict[str, list[LearningResource]] = {}
    resource_slot_keys: dict[str, str] = {}
    for resource in run_resources:
        if resource.representation != CANONICAL_TEXT:
            flag(PublishIncompleteReason.UNSUPPORTED_REPRESENTATION)
            continue
        slot_key, lineage_conflict = _resolve_slot_key(
            resource, family_to_spec=family_to_spec, resources_by_id=resources_by_id
        )
        if lineage_conflict:
            flag(PublishIncompleteReason.LINEAGE_CONFLICT)
            continue
        if slot_key is None:
            flag(PublishIncompleteReason.LOGICAL_IDENTITY_MISSING)
            continue
        slot = slots.get(slot_key)
        if slot is None:
            # A resource version that references a spec outside this run's
            # frozen scope cannot be counted as a confirmed logical slot.
            slot = _Slot(key=slot_key, in_denominator=False)
            slots[slot_key] = slot
            flag(PublishIncompleteReason.SPEC_REQUEST_MISMATCH)
        slot_resources.setdefault(slot_key, []).append(resource)
        resource_slot_keys[resource.resource_id] = slot_key

    executions_by_spec: dict[str, ResourceExecutionRecord] = {}
    for execution in run_executions:
        if execution.representation != CANONICAL_TEXT:
            flag(PublishIncompleteReason.UNSUPPORTED_REPRESENTATION)
            continue
        current = executions_by_spec.get(execution.resource_spec_id)
        if current is None or int(execution.attempt or 0) >= int(current.attempt or 0):
            executions_by_spec[execution.resource_spec_id] = execution

    for slot_key, slot in slots.items():
        execution = executions_by_spec.get(slot_key)
        preferred_id = execution.resource_id if execution is not None else None
        candidates = slot_resources.get(slot_key, [])
        if preferred_id and preferred_id not in resources_by_id:
            flag(PublishIncompleteReason.RESOURCE_REFERENCE_MISSING)
        elif preferred_id and resource_slot_keys.get(preferred_id) != slot_key:
            # Existence alone is insufficient: an execution must not borrow a
            # sibling slot's publication or user-decision state.
            flag(PublishIncompleteReason.LINEAGE_CONFLICT)
        readable = _readable_published_resource(candidates, preferred_id)
        slot.published = readable is not None
        if slot.published:
            continue
        current = (
            resources_by_id.get(preferred_id)
            if preferred_id and resource_slot_keys.get(preferred_id) == slot_key
            else None
        )
        if current is None and candidates:
            current = sorted(
                candidates, key=lambda item: (-int(item.version or 0), item.resource_id)
            )[0]
        slot.pending = bool(current is not None and current.claim_publish_decision_pending)

    denominator = [slot for slot in slots.values() if slot.in_denominator]
    published = sum(1 for slot in denominator if slot.published)
    total = len(denominator) if request_types is not None else None
    identity_unresolved = (
        PublishIncompleteReason.LOGICAL_IDENTITY_MISSING in reasons
        or PublishIncompleteReason.LINEAGE_CONFLICT in reasons
        or PublishIncompleteReason.RESOURCE_REFERENCE_MISSING in reasons
    )
    pending: int | None = None
    if total is not None and not identity_unresolved:
        pending = sum(1 for slot in denominator if slot.pending)

    ordered_reasons = sorted(reasons, key=lambda reason: _REASON_ORDER[reason])
    if ordered_reasons:
        completeness = PublishCompleteness.PARTIAL
    elif total is None or pending is None:
        # A known denominator and pending count are what make the counters
        # literal; never invent a complete-looking summary without them.
        completeness = PublishCompleteness.PARTIAL
        ordered_reasons = [PublishIncompleteReason.REQUEST_MISSING]
    else:
        completeness = PublishCompleteness.COMPLETE
    unpublished = (
        total - published
        if completeness is PublishCompleteness.COMPLETE and total is not None
        else None
    )

    return RunPublishSummary(
        total=total,
        published=published,
        unpublished=unpublished,
        pending_review=pending,
        completeness=completeness,
        incomplete_reasons=ordered_reasons,
    )


def load_publication_summary(
    *,
    run_id: str,
    request_payload: Mapping[str, object] | None,
    resource_repository: BaseResourceRepository | None,
    specs: Sequence[ResourceSpecRecord] | None = None,
    executions: Sequence[ResourceExecutionRecord] | None = None,
    resources: Sequence[LearningResource] | None = None,
) -> RunPublishSummary:
    """Load only the collections the caller did not already read, then aggregate.

    Each missing collection costs at most one repository call per run.  Storage
    failures propagate unchanged; only a genuinely absent dependency degrades
    to ``unavailable``.
    """

    if resource_repository is None:
        return RunPublishSummary(
            completeness=PublishCompleteness.UNAVAILABLE,
            incomplete_reasons=[PublishIncompleteReason.REPOSITORY_UNAVAILABLE],
        )
    if specs is None:
        specs = resource_repository.list_specs_by_run(run_id)
    if executions is None:
        executions = resource_repository.list_executions_by_run(run_id)
    if resources is None:
        resources = resource_repository.list_by_run(run_id)
    return aggregate_publication_summary(
        run_id=run_id,
        request_payload=request_payload,
        specs=specs,
        executions=executions,
        resources=resources,
    )


__all__ = ["aggregate_publication_summary", "load_publication_summary"]
