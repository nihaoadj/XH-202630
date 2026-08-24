"""Add durable three-tier learner access state without changing old records."""

from __future__ import annotations

import hashlib

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.core.learning_tiers import tier_for_level
from app.db.shared.models import LearnerTierProgressORM


MIGRATION_ID = "20260824_p0_21_learning_tiers"


def _id(*parts: object) -> str:
    raw = "\x1f".join(str(item) for item in parts)
    return f"ltp_{hashlib.sha256(raw.encode()).hexdigest()[:32]}"


def apply_p0_21_learning_tiers_migration(engine: Engine) -> None:
    """Create tier state and conservatively backfill node tier/exemption fields."""
    LearnerTierProgressORM.__table__.create(engine, checkfirst=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "rag_skill_nodes" not in tables:
        return
    with engine.begin() as connection:
        columns = {item["name"] for item in inspector.get_columns("rag_skill_nodes")}
        if "tier" not in columns:
            connection.execute(text("ALTER TABLE rag_skill_nodes ADD COLUMN tier INTEGER"))
        if "learner_curriculum_nodes" in tables:
            curriculum_columns = {item["name"] for item in inspector.get_columns("learner_curriculum_nodes")}
            if "placement_exempt" not in curriculum_columns:
                connection.execute(text("ALTER TABLE learner_curriculum_nodes ADD COLUMN placement_exempt BOOLEAN NOT NULL DEFAULT 0"))
            if "placement_evidence_id" not in curriculum_columns:
                connection.execute(text("ALTER TABLE learner_curriculum_nodes ADD COLUMN placement_evidence_id VARCHAR(128)"))
        if "schema_migrations" in tables and connection.execute(text(
            "SELECT 1 FROM schema_migrations WHERE migration_id=:migration_id"
        ), {"migration_id": MIGRATION_ID}).first():
            return
        rows = connection.execute(text("SELECT node_id, level FROM rag_skill_nodes WHERE tier IS NULL")).fetchall()
        for node_id, level in rows:
            try:
                tier = tier_for_level(level)
            except ValueError:
                raise ValueError(f"skill node {node_id} has unknown level {level!r}") from None
            connection.execute(text("UPDATE rag_skill_nodes SET tier=:tier WHERE node_id=:node_id"), {
                "tier": tier, "node_id": node_id,
            })
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"), {
                "migration_id": MIGRATION_ID,
            })


__all__ = ["apply_p0_21_learning_tiers_migration"]
