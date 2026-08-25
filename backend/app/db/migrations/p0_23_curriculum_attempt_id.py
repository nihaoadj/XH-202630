"""Add the last verified-attempt marker to curriculum progress rows."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260825_p0_23_curriculum_attempt_id"
TABLE_NAME = "learner_curriculum_nodes"
COLUMN_NAME = "last_verified_attempt_id"
INDEX_NAME = "ix_learner_curriculum_nodes_last_verified_attempt_id"


def apply_p0_23_curriculum_attempt_id_migration(engine: Engine) -> None:
    """Bring legacy curriculum tables in line with the current ORM model.

    ``create_all`` does not alter an existing SQLite table, so databases that
    were initialized before the idempotency marker was added need this
    additive column migration. Existing verification history remains intact;
    the new marker is intentionally nullable for old rows.
    """
    if TABLE_NAME not in set(inspect(engine).get_table_names()):
        return

    with engine.begin() as connection:
        columns = {
            row[1]
            for row in connection.exec_driver_sql(f"PRAGMA table_info({TABLE_NAME})").fetchall()
        }
        if COLUMN_NAME not in columns:
            connection.execute(
                text(
                    f"ALTER TABLE {TABLE_NAME} "
                    f"ADD COLUMN {COLUMN_NAME} VARCHAR(128)"
                )
            )
        connection.execute(
            text(
                f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
                f"ON {TABLE_NAME} ({COLUMN_NAME})"
            )
        )

        tables = {
            row[0]
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if "schema_migrations" in tables and not connection.execute(
            text(
                "SELECT 1 FROM schema_migrations "
                "WHERE migration_id=:migration_id"
            ),
            {"migration_id": MIGRATION_ID},
        ).first():
            connection.execute(
                text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                {"migration_id": MIGRATION_ID},
            )


__all__ = ["MIGRATION_ID", "apply_p0_23_curriculum_attempt_id_migration"]
