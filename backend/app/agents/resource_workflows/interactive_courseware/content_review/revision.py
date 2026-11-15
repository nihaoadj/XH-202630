from copy import deepcopy
from app.core.courseware.content_review.inventory import put, strict_generation
from app.models.courseware.content_review import ContentReviewBlocked, RevisionPatchV1


def apply_patch(adapter, prepared, identity, raw, allowed_ids):
    patch = RevisionPatchV1.model_validate(raw)
    ids = [c.item_id for c in patch.changes]
    if patch.identity != identity or len(ids) != len(set(ids)) or not set(ids) <= set(allowed_ids):
        raise ContentReviewBlocked("revision outside allowed fields")
    items = {i.item_id: i for i in prepared.items}
    candidate = deepcopy(prepared.candidate)
    for change in patch.changes:
        item = items[change.item_id]
        if item.origin != "ai" or change.old_value_hash != item.value_hash or len(change.new_value) > item.max_chars:
            raise ContentReviewBlocked("revision source/hash/length invalid")
        put(candidate, item.source.tokens, change.new_value)
    # Full validation before returning; no half-applied candidate escapes.
    return strict_generation(adapter.candidate_model, candidate)
