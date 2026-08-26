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
        ComponentDefinition("code_block", renderer="code-block", required_fields=("text", "source_refs", "language", "code"), aria_role="region"),
        ComponentDefinition("flashcard", interactive=True, renderer="flashcard", runtime="flashcard", touch_target=True, required_fields=("text", "source_refs", "front", "back")),
        ComponentDefinition("matching", interactive=True, renderer="matching", runtime="matching", touch_target=True, required_fields=("text", "source_refs", "pairs")),
        ComponentDefinition("ordering", interactive=True, renderer="ordering", runtime="ordering", touch_target=True, required_fields=("text", "source_refs", "ordering_items", "correct_order")),
    )
}


# v2 is additive.  Existing v1 artifacts continue to resolve through
# CATALOG_V1; new candidates must opt into the stricter payload contract.
CATALOG_V2 = {
    **CATALOG_V1,
    **{
        item.name: item
        for item in (
            ComponentDefinition("branching_scenario", interactive=True, schema_version="2.0", renderer="branching-scenario", runtime="branching-scenario", required_fields=("text", "source_refs", "start_node_id", "nodes"), aria_role="application", touch_target=True),
            ComponentDefinition("categorization", interactive=True, schema_version="2.0", renderer="categorization", runtime="categorization", required_fields=("text", "source_refs", "categories", "items"), aria_role="application", touch_target=True),
            ComponentDefinition("word_bank_cloze", interactive=True, schema_version="2.0", renderer="word-bank-cloze", runtime="word-bank-cloze", required_fields=("text", "source_refs", "prompt_segments", "blanks", "tokens"), aria_role="application", touch_target=True),
            ComponentDefinition("timeline_explorer", interactive=True, schema_version="2.0", renderer="timeline-explorer", runtime="timeline-explorer", required_fields=("text", "source_refs", "events"), aria_role="application", touch_target=True),
        )
    },
}


# v3 visual components carry data only.  The renderer owns grids, SVG/DOM,
# colors and positioning; payload items remain source-bound labels/values.
CATALOG_V3 = {
    **CATALOG_V2,
    **{
        item.name: item
        for item in (
            ComponentDefinition("metric_strip", schema_version="3.0", renderer="metric-strip", required_fields=("text", "source_refs", "items"), aria_role="list"),
            ComponentDefinition("process_flow", schema_version="3.0", renderer="process-flow", required_fields=("text", "source_refs", "items"), aria_role="list"),
            ComponentDefinition("concept_map", schema_version="3.0", renderer="concept-map", required_fields=("text", "source_refs", "items"), aria_role="figure"),
            ComponentDefinition("evidence_card", schema_version="3.0", renderer="evidence-card", required_fields=("text", "source_refs", "items"), aria_role="note"),
            ComponentDefinition("comparison_table", schema_version="3.0", renderer="comparison-table", required_fields=("text", "source_refs", "items"), aria_role="table"),
            ComponentDefinition("decision_path", schema_version="3.0", renderer="decision-path", required_fields=("text", "source_refs", "items"), aria_role="list"),
            ComponentDefinition("code_steps", schema_version="3.0", renderer="code-steps", required_fields=("text", "source_refs", "items"), aria_role="region"),
            ComponentDefinition("conclusion_bar", schema_version="3.0", renderer="conclusion-bar", required_fields=("text", "source_refs", "items"), aria_role="note"),
        )
    },
}

# Review practice V2 is an additive, platform-rendered interaction family.
# Its answers come from an already audited review payload; the model can never
# substitute a free-form flashcard or choose the component implementation.
CATALOG_V4 = {
    **CATALOG_V3,
    **{
        item.name: item
        for item in (
            ComponentDefinition("review_overview", schema_version="4.0", renderer="review-overview", required_fields=("text", "source_refs", "items"), aria_role="note"),
            ComponentDefinition("review_recall_card", interactive=True, schema_version="4.0", renderer="review-recall", runtime="review-practice", required_fields=("text", "source_refs", "items"), aria_role="region", touch_target=True),
            ComponentDefinition("review_distinction_card", interactive=True, schema_version="4.0", renderer="review-distinction", runtime="review-practice", required_fields=("text", "source_refs", "items"), aria_role="region", touch_target=True),
            ComponentDefinition("review_example_card", interactive=True, schema_version="4.0", renderer="review-example", runtime="review-practice", required_fields=("text", "source_refs", "items"), aria_role="region", touch_target=True),
            ComponentDefinition("review_node_summary", schema_version="4.0", renderer="review-node-summary", required_fields=("text", "source_refs"), aria_role="note"),
            ComponentDefinition("review_reflection", schema_version="4.0", renderer="review-reflection", required_fields=("text", "source_refs", "reason"), aria_role="note"),
            ComponentDefinition("review_completion", interactive=True, schema_version="4.0", renderer="review-completion", runtime="review-practice", required_fields=("text", "source_refs", "items"), aria_role="region", touch_target=True),
        )
    },
}


def component_definition(name: object, schema_version: str = "1.0") -> ComponentDefinition | None:
    if not isinstance(name, str):
        return None
    definition = CATALOG_V4.get(name)
    return definition if definition is not None and definition.schema_version == schema_version else None


def is_registered_component(name: object, schema_version: str = "1.0") -> bool:
    return component_definition(name, schema_version) is not None


def migrate_component_payload(name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize only known historical payloads; never guess unknown versions."""
    version = str(payload.get("schema_version") or "1.0")
    if component_definition(name, version) is None:
        raise ValueError(f"unsupported component schema: {name}:{version}")
    result = dict(payload)
    result["schema_version"] = version
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
    if name == "branching_scenario":
        return _validate_branching(payload)
    if name == "categorization":
        return _validate_categorization(payload)
    if name == "word_bank_cloze":
        segments, blanks, tokens = payload.get("prompt_segments"), payload.get("blanks"), payload.get("tokens")
        if not isinstance(segments, list) or not isinstance(blanks, list) or not isinstance(tokens, list):
            return False
        if not 2 <= len(segments) <= 7 or not 1 <= len(blanks) <= 6 or not 2 <= len(tokens) <= 12:
            return False
        if len(segments) != len(blanks) + 1:
            return False
        blank_ids = [item.get("blank_id") for item in blanks if isinstance(item, dict)]
        token_ids = [item.get("token_id") for item in tokens if isinstance(item, dict)]
        return len(blank_ids) == len(blanks) and len(blank_ids) == len(set(blank_ids)) and len(token_ids) == len(tokens) and len(token_ids) == len(set(token_ids)) and all(item.get("correct_token_id") in token_ids for item in blanks)
    if name == "timeline_explorer":
        events = payload.get("events")
        if not isinstance(events, list) or not 2 <= len(events) <= 10:
            return False
        ids = [item.get("event_id") for item in events if isinstance(item, dict)]
        sequences = [item.get("sequence") for item in events if isinstance(item, dict)]
        return len(ids) == len(events) and len(ids) == len(set(ids)) and len(sequences) == len(events) and len(sequences) == len(set(sequences)) and sequences == sorted(sequences) and all(item.get("source_refs") for item in events)
    if name in {"metric_strip", "process_flow", "concept_map", "evidence_card", "comparison_table", "decision_path", "code_steps", "conclusion_bar"}:
        items = payload.get("items")
        return isinstance(items, list) and 2 <= len(items) <= 8 and all(
            isinstance(item, dict)
            and str(item.get("label") or "").strip()
            and str(item.get("value") or "").strip()
            and item.get("source_refs")
            for item in items
        )
    if name in {"review_overview", "review_completion"}:
        return isinstance(payload.get("items"), list) and bool(payload["items"])
    if name in {"review_recall_card", "review_distinction_card"}:
        items = payload.get("items")
        return isinstance(items, list) and 1 <= len(items) <= 2 and all(
            isinstance(item, dict) and str(item.get("question_id") or "").strip()
            and str(item.get("prompt") or item.get("statement") or "").strip()
            and str(item.get("reference_answer") or item.get("correction") or "").strip()
            for item in items
        )
    if name == "review_example_card":
        items = payload.get("items")
        if items is None and isinstance(payload.get("item"), dict):
            items = [payload["item"]]
        return isinstance(items, list) and 1 <= len(items) <= 2 and all(
            isinstance(item, dict) and str(item.get("question_id") or "").strip() and all(
                str(item.get(key) or "").strip() for key in ("candidate_a", "candidate_b", "positive_candidate", "decisive_boundary")
            ) for item in items
        )
    if name == "review_node_summary":
        return str(payload.get("node_name") or "").strip() and str(payload.get("text") or "").strip()
    if name == "review_reflection":
        return str(payload.get("reason") or "").strip() in {"INSUFFICIENT_DISTINCT_EVIDENCE", "NO_EXPLICIT_CONCEPT_BOUNDARY"}
    return True


def _validate_branching(payload: dict[str, Any]) -> bool:
    nodes = payload.get("nodes")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 8:
        return False
    ids = [item.get("node_id") for item in nodes if isinstance(item, dict)]
    if len(ids) != len(nodes) or len(ids) != len(set(ids)) or payload.get("start_node_id") not in ids:
        return False
    by_id = {item["node_id"]: item for item in nodes}
    for node in nodes:
        if node.get("node_type") not in {"decision", "terminal"} or not node.get("source_refs"):
            return False
        options = node.get("options") or []
        if node["node_type"] == "terminal" and options:
            return False
        if node["node_type"] == "decision" and not 2 <= len(options) <= 4:
            return False
        option_ids = [item.get("option_id") for item in options]
        if len(option_ids) != len(set(option_ids)) or any(item.get("next_node_id") not in by_id or not item.get("source_refs") for item in options):
            return False
    visiting, visited = set(), set()
    def visit(node_id: str) -> bool:
        if node_id in visiting:
            return False
        if node_id in visited:
            return True
        visiting.add(node_id)
        for option in by_id[node_id].get("options") or []:
            if not visit(option["next_node_id"]):
                return False
        visiting.remove(node_id)
        visited.add(node_id)
        return True
    if not visit(payload["start_node_id"]):
        return False
    return len(visited) == len(by_id) and any(item.get("node_type") == "terminal" for item in nodes)


def _validate_categorization(payload: dict[str, Any]) -> bool:
    categories, items = payload.get("categories"), payload.get("items")
    if not isinstance(categories, list) or not isinstance(items, list) or not 2 <= len(categories) <= 5 or not 3 <= len(items) <= 12:
        return False
    category_ids = [item.get("category_id") for item in categories if isinstance(item, dict)]
    item_ids = [item.get("item_id") for item in items if isinstance(item, dict)]
    return len(category_ids) == len(categories) and len(category_ids) == len(set(category_ids)) and len(item_ids) == len(items) and len(item_ids) == len(set(item_ids)) and all(item.get("correct_category_id") in category_ids and item.get("source_refs") for item in items) and all(item.get("source_refs") for item in categories)


def component_asset_matrix(schema_version: str = "1.0") -> dict[str, dict[str, object]]:
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
        for name, definition in CATALOG_V4.items()
        if definition.schema_version == schema_version
    }


__all__ = ["CATALOG_V1", "CATALOG_V2", "CATALOG_V3", "CATALOG_V4", "ComponentDefinition", "component_asset_matrix", "component_definition", "is_registered_component", "migrate_component_payload", "validate_component_payload"]
