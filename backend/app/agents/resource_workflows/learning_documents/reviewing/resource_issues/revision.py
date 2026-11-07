"""Revision work orders and failure-placeholder isolation (T44).

A ``resource_revision[resource_spec_id]`` work order carries everything the
generation node needs to rebuild one spec: the parent binding, one full previous
artifact + structured package, the frozen targets, the open issues, a brief
closed-issue constraint set, the unchanged state and the revision kind.

Ordinary rework, Claim-only rework and ledger-less generation-failure placeholders
are explicitly distinguished; a placeholder is never counted as a valid content
repair and never consumes/resets the ordinary unchanged counter.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.models.reviews.resource_review import (
    ResourceIssueV1,
    ResourceLedgerV1,
    ResourceReviewBindingV1,
)


@dataclass(frozen=True)
class ResourceRevisionWorkOrderV1:
    resource_spec_id: str
    parent_binding: ResourceReviewBindingV1 | None
    parent_resource_id: str | None
    previous_text: str | None
    previous_structured_payload: dict | None
    targets: tuple[str, ...]
    open_issues: tuple[ResourceIssueV1, ...]
    closed_issues: tuple[ResourceIssueV1, ...]
    unchanged: bool
    revision_kind: str
    failed_placeholder: bool = False

    @property
    def claim_only(self) -> bool:
        return self.revision_kind == "claim"

    def as_dict(self) -> dict:
        return {
            "resource_spec_id": self.resource_spec_id,
            "parent_binding": self.parent_binding.model_dump(mode="json") if self.parent_binding else None,
            "parent_resource_id": self.parent_resource_id,
            "previous_text": self.previous_text,
            "previous_structured_payload": self.previous_structured_payload,
            "targets": list(self.targets),
            "open_issues": [item.model_dump(mode="json") for item in self.open_issues],
            "closed_issues": [item.model_dump(mode="json") for item in self.closed_issues],
            "unchanged": self.unchanged,
            "revision_kind": self.revision_kind,
            "claim_only": self.claim_only,
            "failed_placeholder": self.failed_placeholder,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ResourceRevisionWorkOrderV1":
        from app.models.reviews.resource_review import ResourceIssueV1, ResourceReviewBindingV1
        return cls(
            resource_spec_id=data["resource_spec_id"],
            parent_binding=ResourceReviewBindingV1.model_validate(data["parent_binding"])
            if data.get("parent_binding") else None,
            parent_resource_id=data.get("parent_resource_id"),
            previous_text=data.get("previous_text"),
            previous_structured_payload=data.get("previous_structured_payload"),
            targets=tuple(data.get("targets", [])),
            open_issues=tuple(ResourceIssueV1.model_validate(item) for item in data.get("open_issues", [])),
            closed_issues=tuple(ResourceIssueV1.model_validate(item) for item in data.get("closed_issues", [])),
            unchanged=bool(data.get("unchanged", False)),
            revision_kind=data["revision_kind"],
            failed_placeholder=bool(data.get("failed_placeholder", False)),
        )


def build_revision_work_order(
    *,
    resource_spec_id: str,
    resource,
    previous: ResourceLedgerV1 | None,
    revision_kind: str,
    targets: tuple[str, ...],
    failed_placeholder: bool = False,
) -> ResourceRevisionWorkOrderV1:
    """Build the work order for the next generation round of one spec."""
    if revision_kind not in {"ordinary", "claim"}:
        raise ValueError("unknown resource revision kind")
    if previous is None and not failed_placeholder:
        raise ValueError("a rework order requires a previous ledger or a failure placeholder")
    open_issues: tuple[ResourceIssueV1, ...] = ()
    closed_issues: tuple[ResourceIssueV1, ...] = ()
    if previous is not None:
        from .registry import adapter_for
        if (resource_spec_id != previous.binding.resource_spec_id
                or resource.resource_id != previous.binding.resource_id
                or resource.resource_family_id != previous.binding.lineage_id
                or resource.version != previous.binding.version):
            raise ValueError("revision parent resource identity mismatch")
        parent_material = adapter_for(resource.resource_type).build_material(
            resource=resource, evidence=[], spec=None, targets=list(targets))
        if parent_material.artifact_exact_hash != previous.binding.artifact_exact_hash:
            raise ValueError("revision parent artifact hash mismatch")
        open_issues = tuple(item.issue for item in previous.issues if item.status == "open")
        closed_issues = tuple(item.issue for item in previous.issues if item.status == "closed")
    return ResourceRevisionWorkOrderV1(
        resource_spec_id=resource_spec_id,
        parent_binding=previous.binding if previous else None,
        parent_resource_id=previous.binding.resource_id if previous else resource.resource_id,
        previous_text=resource.content_text if previous is not None else None,
        previous_structured_payload=(_structured(resource) if previous is not None else None),
        targets=targets,
        open_issues=open_issues,
        closed_issues=closed_issues,
        unchanged=bool(previous and previous.observations[-1].unchanged),
        revision_kind=revision_kind,
        failed_placeholder=failed_placeholder,
    )


def _structured(resource) -> dict | None:
    for attr in ("practice_guide_payload", "assessment_payload", "review_practice_payload"):
        value = getattr(resource, attr, None)
        if isinstance(value, dict):
            return value
    return None


def failure_placeholder_work_order(
    *,
    resource_spec_id: str,
    resource,
    targets: tuple[str, ...],
    revision_kind: str = "ordinary",
) -> ResourceRevisionWorkOrderV1:
    """A generation failure that produced no valid artifact is a placeholder."""
    return build_revision_work_order(
        resource_spec_id=resource_spec_id, resource=resource, previous=None,
        revision_kind=revision_kind, targets=targets, failed_placeholder=True)
