"""P0-07 additive feedback/profile/path closed-loop migration."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.shared.models import (
    FeedbackDecisionORM,
    FeedbackFollowUpRunORM,
    KnowledgeStateMutationORM,
    LearnerProfileVersionORM,
    LearningAttemptORM,
    LearningAttemptPointResultORM,
    LearningPathMutationORM,
    LearningPathNodeORM,
    LearningPathORM,
)


MIGRATION_ID = "20260811_p0_07_feedback_profile_path_closed_loop"

ADDITIVE_COLUMNS = {
    "learner_profiles": {
        "profile_version": "INTEGER NOT NULL DEFAULT 1",
    },
    "knowledge_states": {
        "attempt_count": "INTEGER NOT NULL DEFAULT 0",
        "last_attempt_id": "VARCHAR(128)",
        "row_version": "INTEGER NOT NULL DEFAULT 1",
    },
}

NEW_TABLES = (
    LearningAttemptORM.__table__,
    LearningAttemptPointResultORM.__table__,
    FeedbackDecisionORM.__table__,
    KnowledgeStateMutationORM.__table__,
    LearnerProfileVersionORM.__table__,
    LearningPathORM.__table__,
    LearningPathNodeORM.__table__,
    LearningPathMutationORM.__table__,
    FeedbackFollowUpRunORM.__table__,
)


def apply_p0_07_feedback_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ADDITIVE_COLUMNS
        if table in tables
    }
    with engine.begin() as connection:
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in tables:
                continue
            for column, ddl in columns.items():
                if column not in existing[table]:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
    for table in NEW_TABLES:
        table.create(bind=engine, checkfirst=True)
    tables = set(inspect(engine).get_table_names())
    if "schema_migrations" in tables:
        with engine.begin() as connection:
            row = connection.execute(
                text("SELECT migration_id FROM schema_migrations WHERE migration_id=:migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if not row:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
