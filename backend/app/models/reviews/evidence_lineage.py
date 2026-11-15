"""Validate resource ancestry before inheriting frozen generation evidence."""
from __future__ import annotations
import hashlib
import json


def evidence_item_hash(item):
    """Match the v1 scope hash, including explicit optional null fields."""
    return hashlib.sha256(json.dumps(
        item.model_dump(mode="json"), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def evidence_from_snapshot(snapshot):
    from app.models.knowledge.knowledge import EvidenceItem, ScoreKind

    fields = snapshot.model_dump(mode="python", exclude={
        "run_id", "retrieval_step_id", "snapshot_hash", "persisted_at",
    })
    fields.update(query=f"sha256:{snapshot.query_hash}", score_kind=ScoreKind(snapshot.score_kind))
    return EvidenceItem.model_validate(fields)


def resource_lineage(resource, get_resource, *, within_run=False, boundary_resource_id=None):
    """Yield this resource and verified ancestors; broken ancestry fails closed."""
    seen = set()
    current = resource
    while current is not None:
        if current.resource_id in seen:
            raise ValueError("cyclic evidence lineage")
        seen.add(current.resource_id)
        yield current
        parent_id = getattr(current, "parent_resource_id", None)
        if not parent_id:
            return
        parent = get_resource(parent_id)
        if parent is None or parent.resource_id != parent_id:
            raise ValueError("missing evidence lineage parent")
        if within_run and parent.run_id != current.run_id:
            if (parent.resource_id != boundary_resource_id or parent.version != current.version - 1
                    or parent.resource_family_id != current.resource_family_id):
                raise ValueError("retry business lineage mismatch")
            return
        for key in ("run_id", "resource_spec_id", "resource_family_id"):
            if getattr(parent, key, None) != getattr(current, key, None):
                raise ValueError("evidence lineage identity mismatch")
        if parent.version != current.version - 1:
            raise ValueError("evidence lineage version mismatch")
        current = parent
