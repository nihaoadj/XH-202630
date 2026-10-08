"""Track retry replacements without deleting failed workflow evidence."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260819_p0_12_superseded_generation_jobs"


def apply_p0_12_superseded_generation_jobs_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    if "generation_jobs" not in set(inspector.get_table_names()):
        return

    with engine.begin() as connection:
        columns = {item["name"] for item in inspector.get_columns("generation_jobs")}
        if "superseded_by_run_id" not in columns:
            connection.execute(
                text("ALTER TABLE generation_jobs ADD COLUMN superseded_by_run_id VARCHAR(128)")
            )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_generation_jobs_superseded_by_run_id "
                "ON generation_jobs(superseded_by_run_id)"
            )
        )
        tables = set(inspector.get_table_names())
        if "schema_migrations" in tables:
            exists = connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE migration_id = :migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if exists is None:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
