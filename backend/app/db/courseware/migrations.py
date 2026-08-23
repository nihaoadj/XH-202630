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
    scene_columns = {column["name"] for column in inspector.get_columns("courseware_scenes")} if "courseware_scenes" in inspector.get_table_names() else set()
    expected_scene_columns = {
        "input_snapshot_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        "agent_version": "VARCHAR(32) NOT NULL DEFAULT 'deterministic-v1'",
        "prompt_version": "VARCHAR(32) NOT NULL DEFAULT 'deterministic-v1'",
        "review_instruction": "VARCHAR(400)",
        "approved_at": "DATETIME",
        "lease_owner": "VARCHAR(96)",
        "lease_expires_at": "DATETIME",
    }
    if scene_columns:
        with engine.begin() as connection:
            for column, ddl in expected_scene_columns.items():
                if column not in scene_columns:
                    connection.execute(text(f"ALTER TABLE courseware_scenes ADD COLUMN {column} {ddl}"))
