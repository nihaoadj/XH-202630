"""Add resource batch identifiers while preserving existing execution runs."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260819_p0_11_resource_batches"


def apply_p0_11_resource_batches_migration(engine: Engine) -> None:
    """Backfill each historical resource and job into its original run batch."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "generation_jobs" in tables:
            columns = {item["name"] for item in inspector.get_columns("generation_jobs")}
            if "batch_id" not in columns:
                connection.execute(text("ALTER TABLE generation_jobs ADD COLUMN batch_id VARCHAR(128)"))
            connection.execute(text("UPDATE generation_jobs SET batch_id = run_id WHERE batch_id IS NULL OR batch_id = ''"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generation_jobs_batch_id ON generation_jobs(batch_id)"))
        if "generated_resources" in tables:
            columns = {item["name"] for item in inspector.get_columns("generated_resources")}
            if "batch_id" not in columns:
                connection.execute(text("ALTER TABLE generated_resources ADD COLUMN batch_id VARCHAR(128)"))
            connection.execute(text("UPDATE generated_resources SET batch_id = run_id WHERE batch_id IS NULL OR batch_id = ''"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generated_resources_batch_id ON generated_resources(batch_id)"))
        if "schema_migrations" in tables:
            row = connection.execute(
                text("SELECT migration_id FROM schema_migrations WHERE migration_id = :migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if row is None:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
