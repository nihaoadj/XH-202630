"""Persist feedback tier recommendations without making them mandatory."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260826_p0_29_feedback_decision_tiers"


def apply_p0_29_feedback_decision_tiers_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if "feedback_decisions" not in tables:
        return
    columns = {item["name"] for item in inspect(engine).get_columns("feedback_decisions")}
    with engine.begin() as connection:
        if "recommended_tier" not in columns:
            connection.execute(text("ALTER TABLE feedback_decisions ADD COLUMN recommended_tier INTEGER"))
        if "remediation_return_tier" not in columns:
            connection.execute(text("ALTER TABLE feedback_decisions ADD COLUMN remediation_return_tier INTEGER"))
        if "tier_transition" not in columns:
            connection.execute(text("ALTER TABLE feedback_decisions ADD COLUMN tier_transition VARCHAR(64)"))
        if "schema_migrations" in tables:
            applied = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
            ).first()
            if applied is None:
                connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["MIGRATION_ID", "apply_p0_29_feedback_decision_tiers_migration"]
