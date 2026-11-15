"""Pure adapter protocol; no gateway, storage, retry or release ownership."""
from typing import Protocol

from app.core.courseware.content_review.evidence import bind_evidence
from app.core.courseware.content_review.inventory import PreparedContent, source_items, strict_generation
from app.models.courseware.content_review import ContentInventoryV1, ContentItemV1, FieldLocatorV1, ReviewItemV1, json_hash


class ContentAdapter(Protocol):
    version: str
    source_key: str
    candidate_model: type
    def validate_source(self, snapshot) -> dict: ...
    def prepare(self, run_id, snapshot, design, candidate) -> PreparedContent: ...
    def validate_projection(self, snapshot, design, candidate, document) -> dict: ...


class DeclaredAdapter:
    """Shared declaration mechanics, never a type dispatch."""
    def refine_design(self, snapshot, design):
        return design

    def validate_source(self, snapshot):
        payload = snapshot[self.source_key]
        raw = {k: v for k, v in payload.items() if k != "payload_hash"}
        strict_generation(self.source_model, raw)
        digest = json_hash(raw)
        if payload.get("payload_hash") != digest or snapshot.get(self.source_key + "_hash") != digest:
            raise ValueError("frozen source payload hash mismatch")
        return payload

    def prepare(self, run_id, snapshot, design, candidate):
        payload = self.validate_source(snapshot)
        candidate = strict_generation(self.candidate_model, candidate) if candidate else {}
        evidence = bind_evidence(snapshot, self.source_key)
        available = [e.evidence_id for e in evidence.items]
        items = []
        inventory = list(source_items(payload, snapshot["resource_id"]))
        for owner, path, maximum, used, rules in self.fields(candidate, design):
            from app.core.courseware.content_review.inventory import at
            value = at(candidate, path)
            locator = FieldLocatorV1(space="candidate", owner_id=owner, tokens=path)
            iid = f"ai:{owner}:{path[-1]}"
            evidence_ids = self.evidence_for(owner, available)
            item = ReviewItemV1(item_id=iid, owner_id=owner, origin="ai" if used else "unused",
                                source=locator, value_hash=json_hash(value), rule_ids=rules if used else [],
                                evidence_ids=evidence_ids, value=value, max_chars=maximum)
            inventory.append(ContentItemV1.model_validate(item.model_dump(exclude={"value", "max_chars"})))
            if used:
                items.append(item)
        classified = {tuple(i.source.tokens) for i in inventory if i.source.space == "candidate"}
        for leaf in source_items(candidate, snapshot["resource_id"]):
            path = tuple(leaf.source.tokens)
            if path in classified:
                continue
            # These are generation-contract controls, validated by schema and
            # adapter ID/component whitelists; they are never semantic prose.
            if not path or (path[-1] not in {"schema_version", "objective_id", "scene_id", "skill_node_id"} and "preferred_component_ids" not in path):
                raise ValueError("unclassified candidate control")
            inventory.append(ContentItemV1(item_id=f"control:{json_hash(path)[:24]}", owner_id=leaf.owner_id,
                origin="derived", source=FieldLocatorV1(space="candidate", owner_id=leaf.owner_id, tokens=list(path)), value_hash=leaf.value_hash))
        if design.get("user_title"):
            value = design["user_title"]
            items.append(ReviewItemV1(item_id="user:course:title", owner_id="user", origin="user",
                source=FieldLocatorV1(space="spec", owner_id="user", tokens=["user_title"]), value_hash=json_hash(value),
                rule_ids=["factual_support", "scope_alignment", "learning_guidance"], evidence_ids=available, value=value, max_chars=160))
        if len(items) > 128:
            raise ValueError("too many AI fields")
        return PreparedContent(candidate, ContentInventoryV1(run_id=run_id, source_id=snapshot["resource_id"],
                               source_schema=payload["schema_version"], adapter_version=self.version, items=inventory), tuple(items), evidence)

    def evidence_for(self, owner, available):
        return available
