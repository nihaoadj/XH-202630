"""Add durable task and immutable candidate-release storage without rewrites."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.courseware.models import CoursewareReleaseORM, CoursewareWorkflowCheckpointORM


MIGRATION_ID = "20260823_p0_15_courseware_execution"


def apply_p0_15_courseware_execution_migration(engine: Engine) -> None:
    """Apply the additive courseware execution schema once on any SQL dialect."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "courseware_generation_jobs" not in tables:
        return
    if "schema_migrations" in tables:
        with engine.begin() as connection:
            if connection.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id = :migration_id"), {
                "migration_id": MIGRATION_ID,
            }).first() is not None:
                return

    # New tables are declared by the ORM but create_all is not a legacy
    # migration mechanism, so create them explicitly for existing databases.
    CoursewareWorkflowCheckpointORM.__table__.create(engine, checkfirst=True)
    CoursewareReleaseORM.__table__.create(engine, checkfirst=True)
    inspector = inspect(engine)
    with engine.begin() as connection:
        _add_columns(connection, inspector, "courseware_generation_jobs", {
            "release_policy": "VARCHAR(16) NOT NULL DEFAULT 'resilient'",
            "next_event_sequence": "INTEGER NOT NULL DEFAULT 1",
            "deadline_at": "DATETIME",
            "cancel_requested_at": "DATETIME",
            "released_release_id": "VARCHAR(96)",
        })
        _add_columns(connection, inspector, "courseware_outbox", {
            "task_kind": "VARCHAR(64) NOT NULL DEFAULT 'courseware.scene.revise'",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'queued'",
            "claimed_by": "VARCHAR(96)", "lease_expires_at": "DATETIME",
            "attempt": "INTEGER NOT NULL DEFAULT 0", "max_attempts": "INTEGER NOT NULL DEFAULT 3",
            "next_attempt_at": "DATETIME", "last_error_code": "VARCHAR(128)",
            "last_error_message": "VARCHAR(512)", "dead_lettered_at": "DATETIME",
        })
        _add_columns(connection, inspector, "courseware_resources", {"released_release_id": "VARCHAR(96)"})
        _add_columns(connection, inspector, "courseware_artifacts", {
            "release_id": "VARCHAR(96)", "required": "INTEGER NOT NULL DEFAULT 1",
            "artifact_status": "VARCHAR(32) NOT NULL DEFAULT 'ready'",
        })
        _add_columns(connection, inspector, "courseware_scene_revisions", {"idempotency_key": "VARCHAR(160)"})
        _assert_no_duplicate_events(connection, tables)
        _assert_no_duplicate_revisions(connection, tables)
        _backfill_event_counters(connection, tables)
        _unique_index(connection, "uq_courseware_event_sequence", "courseware_events", "run_id, event_sequence", tables)
        _unique_index(connection, "uq_courseware_scene_revision", "courseware_scene_revisions", "scene_id, revision_no", tables)
        _unique_index(connection, "uq_courseware_scene_revision_key", "courseware_scene_revisions", "idempotency_key", tables)
        _unique_index(connection, "uq_courseware_release_candidate", "courseware_releases", "run_id, candidate_no", tables)
        _unique_index(connection, "uq_courseware_checkpoint", "courseware_workflow_checkpoints", "run_id, stage, attempt", tables)
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"), {
                "migration_id": MIGRATION_ID,
            })


def _add_columns(connection, inspector, table: str, columns: dict[str, str]) -> None:
    if table not in {entry["name"] for entry in inspector.get_table_names() if isinstance(entry, dict)}:
        # SQLAlchemy Inspector returns names from get_table_names; retain this
        # branch only for mock inspectors used by focused migration tests.
        table_names = set(inspector.get_table_names())
        if table not in table_names:
            return
    existing = {column["name"] for column in inspector.get_columns(table)}
    for name, ddl in columns.items():
        if name not in existing:
            connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))


def _assert_no_duplicate_events(connection, tables: set[str]) -> None:
    if "courseware_events" not in tables:
        return
    duplicate = connection.execute(text(
        "SELECT run_id, event_sequence FROM courseware_events "
        "GROUP BY run_id, event_sequence HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("P0_15_DUPLICATE_EVENT_SEQUENCE")


def _assert_no_duplicate_revisions(connection, tables: set[str]) -> None:
    if "courseware_scene_revisions" not in tables:
        return
    duplicate = connection.execute(text(
        "SELECT scene_id, revision_no FROM courseware_scene_revisions "
        "GROUP BY scene_id, revision_no HAVING COUNT(*) > 1 LIMIT 1"
    )).first()
    if duplicate:
        raise RuntimeError("P0_15_DUPLICATE_SCENE_REVISION")


def _backfill_event_counters(connection, tables: set[str]) -> None:
    if "courseware_generation_jobs" not in tables:
        return
    if "courseware_events" in tables:
        connection.execute(text(
            "UPDATE courseware_generation_jobs SET next_event_sequence = CASE "
            "WHEN next_event_sequence > COALESCE((SELECT MAX(event_sequence) + 1 "
            "FROM courseware_events e WHERE e.run_id = courseware_generation_jobs.run_id), 1) "
            "THEN next_event_sequence ELSE COALESCE((SELECT MAX(event_sequence) + 1 "
            "FROM courseware_events e WHERE e.run_id = courseware_generation_jobs.run_id), 1) END"
        ))
    else:
        connection.execute(text(
            "UPDATE courseware_generation_jobs SET next_event_sequence = "
            "CASE WHEN next_event_sequence IS NULL OR next_event_sequence < 1 THEN 1 ELSE next_event_sequence END"
        ))


def _unique_index(connection, name: str, table: str, columns: str, tables: set[str]) -> None:
    if table not in tables:
        return
    connection.execute(text(f"CREATE UNIQUE INDEX IF NOT EXISTS {name} ON {table} ({columns})"))
