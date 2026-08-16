"""Additive runtime performance/finalization observability migration."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260810_p0_07_runtime_observability"
ADDITIVE_COLUMNS = {
    "retrieval_profile": "JSON DEFAULT '{}'",
    "workflow_elapsed_ms": "INTEGER",
    "workflow_remaining_ms": "INTEGER",
}


def apply_p0_07_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "agent_steps" not in tables:
        return
    existing = {column["name"] for column in inspector.get_columns("agent_steps")}
    with engine.begin() as connection:
        for column, ddl in ADDITIVE_COLUMNS.items():
            if column not in existing:
                connection.execute(text(f"ALTER TABLE agent_steps ADD COLUMN {column} {ddl}"))
        if "schema_migrations" in tables:
            row = connection.execute(
                text("SELECT migration_id FROM schema_migrations WHERE migration_id=:migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if not row:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
