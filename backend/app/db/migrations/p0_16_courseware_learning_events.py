"""Additive SQLite-safe learning event envelope and projection storage."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from app.db.courseware.models import CoursewareLearningEventORM

MIGRATION_ID = "20260823_p0_16_courseware_learning_events"

def apply_p0_16_courseware_learning_events_migration(engine: Engine) -> None:
    tables = set(inspect(engine).get_table_names())
    if "courseware_generation_jobs" not in tables:
        return
    CoursewareLearningEventORM.__table__.create(engine, checkfirst=True)
    if "schema_migrations" in tables:
        with engine.begin() as conn:
            if conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).first():
                return
            conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})
