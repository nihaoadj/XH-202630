"""Add and safely backfill courseware feedback-batch ownership."""

from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260823_p0_18_courseware_batch_integrity"


def _valid_batch(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value if value and len(value) <= 128 else None


def apply_p0_18_courseware_batch_integrity_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {"courseware_generation_jobs", "courseware_resources"}
    if not required <= tables:
        return
    if "schema_migrations" in tables:
        with engine.begin() as connection:
            if connection.execute(
                text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"),
                {"id": MIGRATION_ID},
            ).first():
                return
    with engine.begin() as connection:
        job_columns = {column["name"] for column in inspect(engine).get_columns("courseware_generation_jobs")}
        resource_columns = {column["name"] for column in inspect(engine).get_columns("courseware_resources")}
        if "source_batch_id" not in job_columns:
            connection.execute(text("ALTER TABLE courseware_generation_jobs ADD COLUMN source_batch_id VARCHAR(128)"))
        if "batch_id" not in resource_columns:
            connection.execute(text("ALTER TABLE courseware_resources ADD COLUMN batch_id VARCHAR(128)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_courseware_job_source_batch_id ON courseware_generation_jobs (source_batch_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_courseware_resource_batch_id ON courseware_resources (batch_id)"))
        _backfill(connection, tables)
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


def _backfill(connection, tables: set[str]) -> None:
    if "courseware_source_links" not in tables:
        return
    rows = connection.execute(text(
        "SELECT csl.courseware_resource_id, csl.source_snapshot, cwr.run_id "
        "FROM courseware_source_links csl JOIN courseware_resources cwr "
        "ON cwr.resource_id = csl.courseware_resource_id"
    )).mappings().all()
    by_resource: dict[str, list[tuple[str | None, str]]] = {}
    for row in rows:
        try:
            snapshot = json.loads(row["source_snapshot"] or "{}")
        except (TypeError, ValueError, json.JSONDecodeError):
            batch_id = None
        else:
            batch_id = _valid_batch(snapshot.get("batch_id")) if isinstance(snapshot, dict) else None
        by_resource.setdefault(str(row["courseware_resource_id"]), []).append((batch_id, str(row["run_id"])))
    for resource_id, values in by_resource.items():
        batches = {value for value, _ in values if value is not None}
        if len(values) == 0 or len(batches) != 1 or any(value is None for value, _ in values):
            continue
        batch_id = next(iter(batches))
        connection.execute(text("UPDATE courseware_resources SET batch_id=:batch WHERE resource_id=:resource"), {"batch": batch_id, "resource": resource_id})
        run_ids = {run_id for _, run_id in values}
        if len(run_ids) == 1:
            connection.execute(text("UPDATE courseware_generation_jobs SET source_batch_id=:batch WHERE run_id=:run_id"), {"batch": batch_id, "run_id": next(iter(run_ids))})
