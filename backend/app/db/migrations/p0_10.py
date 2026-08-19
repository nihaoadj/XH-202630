"""Persist assessment question banks in the SQL catalog."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.models import AssessmentQuestionORM


MIGRATION_ID = "20260819_p0_10_assessment_question_catalog"


def apply_p0_10_migration(engine: Engine) -> None:
    """Create the runtime assessment-question projection on existing databases."""
    AssessmentQuestionORM.__table__.create(bind=engine, checkfirst=True)
    if "schema_migrations" not in inspect(engine).get_table_names():
        return
    with engine.begin() as connection:
        row = connection.execute(
            text("SELECT migration_id FROM schema_migrations WHERE migration_id = :migration_id"),
            {"migration_id": MIGRATION_ID},
        ).first()
        if row is None:
            connection.execute(
                text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                {"migration_id": MIGRATION_ID},
            )
