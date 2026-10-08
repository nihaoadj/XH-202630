"""Keep historical personalized correction packages in their source resource batch."""

from __future__ import annotations

import json

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260825_p0_24_correction_package_batches"


def _payload(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        decoded = json.loads(value)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def apply_p0_24_correction_package_batches_migration(engine: Engine) -> None:
    """Backfill only correction runs with an unambiguous source batch.

    A correction package is extra material for the assessed resource group, not
    a newly-confirmed node group.  Earlier runs used their own run ID as their
    batch ID, so both the job and published artifact need the same correction.
    """
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    required = {"generation_jobs", "generated_resources"}
    if not required <= tables:
        return
    with engine.begin() as connection:
        if "schema_migrations" in tables and connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
        ).first():
            return
        columns = {column["name"] for column in inspector.get_columns("generation_jobs")}
        if not {"run_id", "batch_id", "request_payload"} <= columns:
            return
        jobs = connection.execute(text(
            "SELECT run_id, batch_id, request_payload FROM generation_jobs"
        )).mappings().all()
        batch_by_run = {str(row["run_id"]): str(row["batch_id"] or row["run_id"]) for row in jobs}
        for row in jobs:
            payload = _payload(row["request_payload"])
            constraints = payload.get("constraints") if isinstance(payload.get("constraints"), dict) else {}
            snapshot = constraints.get("correction_focus_snapshot")
            source_run_id = snapshot.get("source_run_id") if isinstance(snapshot, dict) else None
            source_batch_id = batch_by_run.get(str(source_run_id or ""))
            if not source_batch_id:
                continue
            run_id = str(row["run_id"])
            if str(row["batch_id"] or "") == source_batch_id:
                continue
            connection.execute(text(
                "UPDATE generation_jobs SET batch_id=:batch_id WHERE run_id=:run_id"
            ), {"batch_id": source_batch_id, "run_id": run_id})
            connection.execute(text(
                "UPDATE generated_resources SET batch_id=:batch_id WHERE run_id=:run_id"
            ), {"batch_id": source_batch_id, "run_id": run_id})
        if "schema_migrations" in tables:
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["MIGRATION_ID", "apply_p0_24_correction_package_batches_migration"]
