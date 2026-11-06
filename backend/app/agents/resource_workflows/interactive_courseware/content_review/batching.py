"""Deterministic packing, complete input and schema-bounded output estimates."""
from dataclasses import dataclass
from math import ceil

from app.models.courseware.content_review import ContentReviewBlocked, canonical_json, json_hash
from .types import ReviewBatch
from .prompts.builder import build_messages


@dataclass(frozen=True)
class TokenEstimatorProfile:
    id: str = "fixture-tokenizer-v1"
    version: str = "1.0"
    # A virtual offline tokenizer, not a production tokenizer claim.
    def count_input_upper_bound(self, messages, schema, mode=None):
        return ceil(len(canonical_json({"messages": [(m.type, m.content) for m in messages], "schema": schema, "mode": str(mode)}).encode("utf-8")) / 4) + 1024

    def count_output_upper_bound(self, bounded_json):
        return ceil(len(bounded_json.encode("utf-8")) / 4) + 128


def resolve_estimator(policy, gateway):
    from app.core.llm.gateway import LLMGateway
    actual = getattr(gateway, "underlying_gateway", gateway)
    if isinstance(actual, LLMGateway) or not getattr(actual, "offline_content_review", False) or policy.estimator_id != "fixture-tokenizer-v1":
        raise ContentReviewBlocked("no verified production token estimator")
    return TokenEstimatorProfile()


def output_upper_json(items, *, revision=False):
    # ensure_ascii + U+FFFF force the longest JSON escape, including quotes,
    # punctuation, all arrays and all allowed IDs. Use actual per-batch IDs.
    if revision:
        value = {"schema_version": "1.0", "identity": "f"*64, "changes": [
            {"schema_version": "1.0", "item_id": i.item_id, "old_value_hash": i.value_hash, "new_value": "\U0010ffff"*i.max_chars} for i in items]}
    else:
        value = {"schema_version": "1.0", "batch_id": "b"*96, "identity": "f"*64, "value_hash": "f"*64, "results": []}
        for item in items:
            import json
            eids = sorted(item.evidence_ids, key=lambda eid: len(json.dumps(eid, ensure_ascii=True)), reverse=True)[:4]
            # Repeated IDs are invalid, so distinct longest permitted IDs bound
            # every valid reference list without 256-character guesses.
            rules = [{"schema_version": "1.0", "rule_id": r, "verdict": "insufficient_evidence", "evidence_ids": eids,
                      "problems": [{"schema_version": "1.0", "code": "misleading_guidance", "severity": "warning", "reason": "\U0010ffff"*160}],
                      "factual_support": "insufficient_evidence", "reason": ""} for r in item.rule_ids]
            value["results"].append({"schema_version": "1.0", "item_id": item.item_id, "value_hash": item.value_hash, "rules": rules})
    import json
    return json.dumps(value, ensure_ascii=True, separators=(",", ":"))


def plan_batches(prepared, identity, policy, profile, estimator, *, revision=False):
    items = sorted(prepared.items, key=lambda i: i.item_id)
    by_id = {i.item_id: i for i in items}
    groups = []
    unseen = set(by_id)
    while unseen:
        group = {min(unseen)}
        while True:
            linked = group | {d for iid in group for d in by_id[iid].dependency_ids if d in by_id} | {iid for iid in unseen if set(by_id[iid].dependency_ids) & group}
            if linked == group:
                break
            group = linked
        unseen -= group
        groups.append(tuple(by_id[iid] for iid in sorted(group)))
    def build(batch_items, index):
        ids = {eid for item in batch_items for eid in item.evidence_ids}
        evidence = tuple(e for e in prepared.evidence.items if e.evidence_id in ids)
        batch_id = f"content:{index}:{json_hash([i.item_id for i in batch_items])[:16]}"
        value_hash = json_hash([(i.item_id, i.value_hash) for i in batch_items])
        payload = {"batch_id": batch_id, "identity": identity, "value_hash": value_hash,
                   "items": [i.model_dump(mode="json") for i in batch_items], "evidence": [e.model_dump(mode="json") for e in evidence],
                   "global_values": prepared.candidate}
        messages = build_messages(profile, {r for i in batch_items for r in i.rule_ids}, payload)
        output = estimator.count_output_upper_bound(output_upper_json(batch_items, revision=revision))
        input_tokens = estimator.count_input_upper_bound(messages, profile.schema.model_json_schema())
        return ReviewBatch(batch_id, identity, value_hash, tuple(batch_items), evidence, messages, input_tokens, output)
    batches = []; current = ()
    def fits(batch):
        return batch.output_tokens <= policy.max_output_tokens and batch.input_tokens + batch.output_tokens <= policy.context_tokens
    for group in groups:
        trial = build((*current, *group), len(batches))
        if not fits(trial) and current:
            batches.append(build(current, len(batches))); current = ()
        if not fits(build(group, len(batches))):
            raise ContentReviewBlocked("input_budget: dependency group does not fit")
        current = (*current, *group)
    if current:
        batches.append(build(current, len(batches)))
    if len(batches) > policy.max_batches:
        raise ContentReviewBlocked("input_budget: too many complete batches")
    return batches
