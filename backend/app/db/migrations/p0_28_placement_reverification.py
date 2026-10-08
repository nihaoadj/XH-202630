"""Add an explicit re-verification state for initial placement exemptions."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260826_p0_28_placement_reverification"


def apply_p0_28_placement_reverification_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if "learner_curriculum_nodes" not in tables:
        return
    columns = {item["name"] for item in inspect(engine).get_columns("learner_curriculum_nodes")}
    with engine.begin() as connection:
        if "placement_verification_required" not in columns:
            connection.execute(text(
                "ALTER TABLE learner_curriculum_nodes "
                "ADD COLUMN placement_verification_required BOOLEAN NOT NULL DEFAULT 0"
            ))
        if "schema_migrations" in tables:
            applied = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"),
                {"id": MIGRATION_ID},
            ).first()
            if applied is None:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"),
                    {"id": MIGRATION_ID},
                )


__all__ = ["MIGRATION_ID", "apply_p0_28_placement_reverification_migration"]
