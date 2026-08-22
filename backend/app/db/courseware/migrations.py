"""Forward-compatible schema adjustments for existing courseware databases."""

from sqlalchemy import inspect, text


def migrate_sqlite_courseware(engine) -> None:
    inspector = inspect(engine)
    if "courseware_generation_jobs" not in inspector.get_table_names():
        return
    existing = {column["name"] for column in inspector.get_columns("courseware_generation_jobs")}
    if "publish_mode" not in existing:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE courseware_generation_jobs "
                "ADD COLUMN publish_mode VARCHAR(16) NOT NULL DEFAULT 'manual'"
            ))
