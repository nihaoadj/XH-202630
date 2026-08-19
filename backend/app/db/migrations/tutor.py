"""Additive migration for durable Tutor sessions and turns."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.models import TutorSessionORM, TutorTurnORM


MIGRATION_ID = "20260819_tutor_sessions_turns"
NEW_TABLES = (
    TutorSessionORM.__table__,
    TutorTurnORM.__table__,
)


def apply_tutor_migration(engine: Engine) -> None:
    """Create only missing Tutor tables and record the migration idempotently."""

    for table in NEW_TABLES:
        table.create(bind=engine, checkfirst=True)

    if "schema_migrations" not in set(inspect(engine).get_table_names()):
        return
    with engine.begin() as connection:
        row = connection.execute(
            text(
                "SELECT migration_id FROM schema_migrations "
                "WHERE migration_id=:migration_id"
            ),
            {"migration_id": MIGRATION_ID},
        ).first()
        if not row:
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (migration_id) "
                    "VALUES (:migration_id)"
                ),
                {"migration_id": MIGRATION_ID},
            )
