"""Bounded dynamic extraction data. No external Evidence enters this payload."""
from app.models.reviews.claim_extraction import content_digest


def extraction_payload(text, resource, batch, policy, allowed_nodes):
    nodes = sorted(set(allowed_nodes))
    if len(nodes) > 256 or any(not isinstance(n, str) or len(n) > 256 for n in nodes):
        raise ValueError("extraction knowledge label boundary exceeded")
    if len(resource.resource_id) > 128 or len(resource.resource_type) > 128:
        raise ValueError("extraction resource identity exceeds private contract")
    return {
        "resource_id": resource.resource_id,
        "resource_version": resource.version,
        "resource_type": resource.resource_type,
        "content_hash": content_digest(text),
        "batch_id": batch.batch_id,
        "max_candidates": policy.batch_claims,
        "allowed_knowledge_point_ids": nodes,
        # Unit/context spans use their own field names: the claim output schema
        # also exposes source_start/source_end, but those are unit-local (0-based)
        # offsets. Reusing the same names here made the model copy the absolute
        # unit offsets into claims, which validate_output then rejected as
        # "outside target" (T36 live run 10d9243a).
        "target_units": [dict(unit_id=u.unit_id, kind=u.kind, unit_start=u.start, unit_end=u.end,
                              text=text[u.start:u.end]) for u in batch.units],
        "read_only_context": [dict(context_start=s.start, context_end=s.end, text=text[s.start:s.end]) for s in batch.context],
    }


def extraction_payload_v2(text, resource, batch, policy, allowed_nodes):
    """Neutral-v2 payload: unit text only, no absolute coordinates for the model.

    The server keeps the frozen unit spans for locating; the model never sees
    ``unit_start``/``unit_end`` and therefore cannot copy them as offsets.
    """
    nodes = sorted(set(allowed_nodes))
    if len(nodes) > 256 or any(not isinstance(n, str) or len(n) > 256 for n in nodes):
        raise ValueError("extraction knowledge label boundary exceeded")
    if len(resource.resource_id) > 128 or len(resource.resource_type) > 128:
        raise ValueError("extraction resource identity exceeds private contract")
    return {
        "resource_id": resource.resource_id,
        "resource_version": resource.version,
        "resource_type": resource.resource_type,
        "content_hash": content_digest(text),
        "batch_id": batch.batch_id,
        "max_candidates": policy.batch_claims,
        "allowed_knowledge_point_ids": nodes,
        "target_units": [dict(unit_id=u.unit_id, kind=u.kind, text=text[u.start:u.end]) for u in batch.units],
        "read_only_context": [text[s.start:s.end] for s in batch.context],
    }
