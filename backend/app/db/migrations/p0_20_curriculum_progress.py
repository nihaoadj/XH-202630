"""Add durable learner curriculum progress without changing mastery semantics."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.shared.models import LearnerCurriculumNodeORM


MIGRATION_ID = "20260824_p0_20_curriculum_progress"


def _id(*parts: object) -> str:
    raw = "\x1f".join(str(part) for part in parts)
    return f"lcn_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def _points(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    return [str(item) for item in parsed] if isinstance(parsed, list) else []


def apply_p0_20_curriculum_progress_migration(engine: Engine) -> None:
    """Create and conservatively backfill the curriculum projection.

    Old published resources indicate exposure only; no legacy resource is ever
    promoted to ``completed`` without independently persisted objective evidence.
    """
    LearnerCurriculumNodeORM.__table__.create(engine, checkfirst=True)
    tables = set(inspect(engine).get_table_names())
    if not {"learner_profiles", "rag_skill_nodes"}.issubset(tables):
        return
    with engine.begin() as connection:
        if "schema_migrations" in tables and connection.execute(text(
            "SELECT 1 FROM schema_migrations WHERE migration_id=:migration_id"
        ), {"migration_id": MIGRATION_ID}).first():
            return
        node_rows = connection.execute(text(
            "SELECT knowledge_base_id,node_id,name FROM rag_skill_nodes"
        )).fetchall()
        nodes_by_kb: dict[str, dict[str, str]] = {}
        ids_by_name: dict[str, dict[str, str | None]] = {}
        for kb_id, node_id, name in node_rows:
            nodes_by_kb.setdefault(kb_id, {})[node_id] = name
            prior = ids_by_name.setdefault(kb_id, {}).get(name)
            ids_by_name[kb_id][name] = node_id if prior is None else None
        published: dict[tuple[str, str, str], int] = {}
        if "generated_resources" in tables:
            resources = connection.execute(text(
                "SELECT learner_id,knowledge_points FROM generated_resources WHERE publication_status='published'"
            )).fetchall()
            learner_kbs = dict(connection.execute(text(
                "SELECT learner_id,knowledge_base_id FROM learner_profiles WHERE knowledge_base_id IS NOT NULL"
            )).fetchall())
            for learner_id, raw_points in resources:
                kb_id = learner_kbs.get(learner_id)
                if not kb_id:
                    continue
                node_names = nodes_by_kb.get(kb_id, {})
                for point in set(_points(raw_points)):
                    node_id = point if point in node_names else ids_by_name.get(kb_id, {}).get(point)
                    if node_id:
                        key = (learner_id, kb_id, node_id)
                        published[key] = published.get(key, 0) + 1
        profiles = connection.execute(text(
            "SELECT learner_id,knowledge_base_id FROM learner_profiles WHERE knowledge_base_id IS NOT NULL"
        )).fetchall()
        now = datetime.now(timezone.utc)
        for learner_id, kb_id in profiles:
            for node_id in nodes_by_kb.get(kb_id, {}):
                count = published.get((learner_id, kb_id, node_id), 0)
                exists = connection.execute(text(
                    "SELECT 1 FROM learner_curriculum_nodes WHERE learner_id=:learner "
                    "AND knowledge_base_id=:kb AND skill_node_id=:node"
                ), {"learner": learner_id, "kb": kb_id, "node": node_id}).first()
                if exists:
                    continue
                connection.execute(text(
                    "INSERT INTO learner_curriculum_nodes "
                    "(curriculum_node_id,learner_id,knowledge_base_id,skill_node_id,progress_status,wait_rounds,"
                    "published_resource_count,verified_attempt_count,row_version,last_published_at) "
                    "VALUES (:id,:learner,:kb,:node,:status,0,:count,0,1,:published_at)"
                ), {"id": _id(learner_id, kb_id, node_id), "learner": learner_id, "kb": kb_id,
                    "node": node_id, "status": "exposed" if count else "unplanned", "count": count,
                    "published_at": now if count else None})
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                               {"migration_id": MIGRATION_ID})


__all__ = ["apply_p0_20_curriculum_progress_migration"]
