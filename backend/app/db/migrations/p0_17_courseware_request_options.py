"""Persist optional AI-first courseware composition preferences additively."""

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260823_p0_17_courseware_request_options"


def apply_p0_17_courseware_request_options_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    if "courseware_generation_jobs" not in set(inspector.get_table_names()):
        return
    with engine.begin() as connection:
        if "schema_migrations" in set(inspector.get_table_names()) and connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
        ).first():
            return
        columns = {column["name"] for column in inspector.get_columns("courseware_generation_jobs")}
        if "request_options" not in columns:
            connection.execute(text("ALTER TABLE courseware_generation_jobs ADD COLUMN request_options JSON NOT NULL DEFAULT '{}'"))
        if "schema_migrations" in set(inspector.get_table_names()):
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})
