"""Normalize learner-facing skill labels while retaining canonical node IDs elsewhere."""

from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260821_p0_14_profile_skill_node_labels"


def _as_list(value) -> list[str]:
    try:
        parsed = json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        parsed = []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def _display_labels(values: list[str], names_by_id: dict[str, str]) -> list[str]:
    ids_by_name = {name: node_id for node_id, name in names_by_id.items()}
    normalized = []
    for value in values:
        node_id = value if value in names_by_id else ids_by_name.get(value)
        if node_id is None:
            # Already-migrated display labels are recognized by their trailing
            # canonical ID, so rerunning migration remains idempotent.
            for candidate_id in names_by_id:
                if value.endswith(f"（{candidate_id}）"):
                    node_id = candidate_id
                    break
        normalized.append(names_by_id[node_id] if node_id else value)
    return list(dict.fromkeys(normalized))


def apply_p0_14_profile_skill_node_labels_migration(engine: Engine) -> None:
    """Replace legacy node IDs in profile display fields with node names.

    Feedback decisions retain node IDs for routing; learner profile weak/strong
    point lists show each capability once using its learner-facing name.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {"learner_profiles", "rag_skill_nodes", "schema_migrations"}
    if not required.issubset(tables):
        return

    with engine.begin() as connection:
        applied = connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id = :migration_id"),
            {"migration_id": MIGRATION_ID},
        ).first()
        if applied is not None:
            return

        nodes = connection.execute(text(
            "SELECT knowledge_base_id, node_id, name FROM rag_skill_nodes"
        )).fetchall()
        names_by_base: dict[str, dict[str, str]] = {}
        for knowledge_base_id, node_id, name in nodes:
            names_by_base.setdefault(knowledge_base_id, {})[node_id] = name

        profiles = connection.execute(text(
            "SELECT learner_id, knowledge_base_id, weak_points, strong_points FROM learner_profiles"
        )).fetchall()
        for learner_id, knowledge_base_id, weak_points, strong_points in profiles:
            names_by_id = names_by_base.get(knowledge_base_id, {})
            normalized_weak = _display_labels(_as_list(weak_points), names_by_id)
            normalized_strong = _display_labels(_as_list(strong_points), names_by_id)
            if normalized_weak != _as_list(weak_points) or normalized_strong != _as_list(strong_points):
                connection.execute(text(
                    "UPDATE learner_profiles SET weak_points = :weak_points, strong_points = :strong_points "
                    "WHERE learner_id = :learner_id"
                ), {
                    "learner_id": learner_id,
                    "weak_points": json.dumps(normalized_weak, ensure_ascii=False),
                    "strong_points": json.dumps(normalized_strong, ensure_ascii=False),
                })
        connection.execute(
            text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
            {"migration_id": MIGRATION_ID},
        )
