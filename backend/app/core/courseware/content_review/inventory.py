"""Strict generation shape, stable owners and source/AI consumption inventory."""
from dataclasses import dataclass
from typing import Any

from app.models.courseware.content_review import (
    ContentInventoryV1, ContentItemV1, ContentReviewBlocked, FieldLocatorV1, ReviewItemV1, json_hash,
)


@dataclass(frozen=True)
class PreparedContent:
    candidate: dict
    inventory: ContentInventoryV1
    items: tuple[ReviewItemV1, ...]
    evidence: Any


def strict_generation(model, raw):
    """Existing generation DTOs allow extras; private candidates must reject them."""
    def check(value, schema, defs):
        while "$ref" in schema or "anyOf" in schema:
            if "$ref" in schema:
                schema = defs[schema["$ref"].rsplit("/", 1)[-1]]
            else:
                schema = next((s for s in schema["anyOf"] if s.get("type") != "null"), {}) if value is not None else {}
        if isinstance(value, dict):
            props = schema.get("properties", {})
            if set(value) - set(props):
                raise ContentReviewBlocked("unclassified generation field")
            for k, v in value.items():
                check(v, props[k], defs)
        if isinstance(value, list):
            for v in value:
                check(v, schema.get("items", {}), defs)
    schema = model.model_json_schema()
    check(raw, schema, schema.get("$defs", {}))
    return model.model_validate(raw).model_dump(mode="json")


def source_items(value, owner, tokens=()):
    if isinstance(value, dict):
        owner = str(value.get("question_id") or value.get("skill_node_id") or value.get("step_id") or owner)
        for key, child in value.items():
            yield from source_items(child, owner, (*tokens, key))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from source_items(child, owner, (*tokens, index))
    else:
        # Value-bound stable IDs for collections without natural IDs; locators
        # retain position, while identity never rests on an index alone.
        iid = f"source:{owner}:{json_hash([tokens, value])[:24]}"
        yield ContentItemV1(item_id=iid, owner_id=owner, origin="source",
                            source=FieldLocatorV1(space="source", owner_id=owner, tokens=list(tokens)),
                            value_hash=json_hash(value))


def at(value, tokens):
    for token in tokens:
        value = value[token]
    return value


def put(value, tokens, new_value):
    target = value
    for token in tokens[:-1]:
        target = target[token]
    target[tokens[-1]] = new_value
