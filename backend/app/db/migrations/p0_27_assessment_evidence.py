"""Add auditable assessment metadata to append-only mastery evidence."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260826_p0_27_assessment_evidence"


def apply_p0_27_assessment_evidence_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if "ability_state_events" not in tables:
        return
    columns = {item["name"] for item in inspect(engine).get_columns("ability_state_events")}
    with engine.begin() as connection:
        if "evidence_metadata" not in columns:
            connection.execute(text(
                "ALTER TABLE ability_state_events ADD COLUMN evidence_metadata JSON NOT NULL DEFAULT '{}'"
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


__all__ = ["MIGRATION_ID", "apply_p0_27_assessment_evidence_migration"]
