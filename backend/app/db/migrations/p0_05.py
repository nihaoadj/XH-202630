"""P0-05 additive resource review and publication migration."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260807_p0_05_generation_review_revision"


SQLITE_COLUMNS = {
    "generated_resources": {
        "publication_status": "VARCHAR(32) NOT NULL DEFAULT 'unpublished'",
        "published_at": "DATETIME",
    },
    "resource_reviews": {
        "revision_instructions": "JSON DEFAULT '[]'",
        "review_hash": "VARCHAR(64)",
    },
}


def apply_p0_05_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    definitions = {
        table: {
            column: (
                ddl.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
                if engine.url.get_backend_name() == "postgresql"
                else ddl
            )
            for column, ddl in columns.items()
        }
        for table, columns in SQLITE_COLUMNS.items()
    }
    existing_by_table = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in definitions
        if table in tables
    }
    with engine.begin() as connection:
        for table, columns in definitions.items():
            if table not in tables:
                continue
            for column, ddl in columns.items():
                if column not in existing_by_table[table]:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        if "generated_resources" in tables:
            connection.execute(
                text(
                    "UPDATE generated_resources SET publication_status = 'unpublished' "
                    "WHERE publication_status IS NULL"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_generated_resources_publication "
                    "ON generated_resources (learner_id, publication_status, created_at)"
                )
            )
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_generated_resources_run_version "
                    "ON generated_resources (run_id, resource_type, version)"
                )
            )
        if "resource_reviews" in tables:
            connection.execute(
                text(
                    "CREATE INDEX IF NOT EXISTS ix_resource_reviews_review_hash "
                    "ON resource_reviews (review_hash)"
                )
            )
        if "schema_migrations" in tables:
            already_applied = connection.execute(
                text(
                    "SELECT migration_id FROM schema_migrations "
                    "WHERE migration_id = :migration_id"
                ),
                {"migration_id": MIGRATION_ID},
            ).first()
            if not already_applied:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
