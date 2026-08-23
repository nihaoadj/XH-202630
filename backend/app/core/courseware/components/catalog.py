"""Versioned, platform-owned component catalog.

Each entry describes the complete renderer/runtime contract for one component;
learner/model data can only select an entry by its registered name and version.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ComponentDefinition:
    name: str
    interactive: bool = False
    schema_version: str = "1.0"
    renderer: str = "text"
    runtime: str = "static"
    required_fields: tuple[str, ...] = ("text", "source_refs")
    aria_role: str = "paragraph"
    keyboard_support: bool = True
    touch_target: bool = False


CATALOG_V1 = {
    item.name: item
    for item in (
        ComponentDefinition("callout", renderer="callout", aria_role="note"),
        ComponentDefinition("key_point", renderer="key-point", aria_role="note"),
        ComponentDefinition("compare", renderer="compare", aria_role="region"),
        ComponentDefinition("steps", interactive=True, renderer="steps", runtime="checkbox", touch_target=True),
        ComponentDefinition("ordered_steps", interactive=True, renderer="ordered-steps", runtime="checkbox", touch_target=True),
        ComponentDefinition("single_choice", interactive=True, renderer="choice", runtime="single-choice", touch_target=True),
        ComponentDefinition("multiple_choice", interactive=True, renderer="choice", runtime="multiple-choice", touch_target=True),
        ComponentDefinition("recap", renderer="recap", aria_role="note"),
        ComponentDefinition("flashcard", interactive=True, renderer="flashcard", runtime="flashcard", touch_target=True, required_fields=("text", "source_refs", "front", "back")),
        ComponentDefinition("matching", interactive=True, renderer="matching", runtime="matching", touch_target=True, required_fields=("text", "source_refs", "pairs")),
        ComponentDefinition("ordering", interactive=True, renderer="ordering", runtime="ordering", touch_target=True, required_fields=("text", "source_refs", "ordering_items", "correct_order")),
    )
}


def component_definition(name: object, schema_version: str = "1.0") -> ComponentDefinition | None:
    if not isinstance(name, str):
        return None
    definition = CATALOG_V1.get(name)
    return definition if definition is not None and definition.schema_version == schema_version else None


def is_registered_component(name: object, schema_version: str = "1.0") -> bool:
    return component_definition(name, schema_version) is not None


def migrate_component_payload(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize only known historical payloads; never guess unknown versions."""
    version = str(payload.get("schema_version") or "1.0")
    if component_definition(name, version) is None:
        raise ValueError(f"unsupported component schema: {name}:{version}")
    result = dict(payload)
    result["schema_version"] = "1.0"
    result.setdefault("source_refs", [])
    return result


def validate_component_payload(name: str, payload: dict[str, Any]) -> bool:
    if component_definition(name, str(payload.get("schema_version") or "1.0")) is None:
        return False
    if not str(payload.get("text") or "").strip():
        return False
    refs = payload.get("source_refs")
    if not isinstance(refs, list) or not all(isinstance(ref, dict) and ref.get("source_resource_id") and ref.get("source_block_ids") for ref in refs):
        return False
    if name == "flashcard":
        return bool(str(payload.get("front") or "").strip() and str(payload.get("back") or "").strip())
    if name == "matching":
        pairs = payload.get("pairs")
        return isinstance(pairs, list) and len(pairs) >= 2 and all(
            isinstance(pair, dict) and str(pair.get("left") or "").strip() and str(pair.get("right") or "").strip()
            for pair in pairs
        )
    if name == "ordering":
        items, correct = payload.get("ordering_items"), payload.get("correct_order")
        return isinstance(items, list) and len(items) >= 2 and isinstance(correct, list) and items == list(dict.fromkeys(items)) and set(items) == set(correct) and len(items) == len(correct)
    return True


def component_asset_matrix() -> dict[str, dict[str, object]]:
    """Return an immutable-test-friendly view of all registered component assets."""
    return {
        name: {
            "schema_version": definition.schema_version,
            "renderer": definition.renderer,
            "runtime": definition.runtime,
            "interactive": definition.interactive,
            "required_fields": definition.required_fields,
            "aria_role": definition.aria_role,
            "keyboard_support": definition.keyboard_support,
            "touch_target": definition.touch_target,
        }
        for name, definition in CATALOG_V1.items()
    }


__all__ = ["CATALOG_V1", "ComponentDefinition", "component_asset_matrix", "component_definition", "is_registered_component", "migrate_component_payload", "validate_component_payload"]
