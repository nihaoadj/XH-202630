"""P0-04 additive lifecycle persistence migration.

This migration deliberately avoids table rebuilds and destructive backfills. Legacy
rows remain queryable with ``replay_completeness=legacy_partial``.
"""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


MIGRATION_ID = "20260730_p0_04_agent_run_persistence"


SQLITE_COLUMNS: dict[str, dict[str, str]] = {
    "agent_runs": {
        "schema_version": "VARCHAR(16) NOT NULL DEFAULT '1.0'",
        "request_hash": "VARCHAR(64)",
        "workflow_status": "VARCHAR(32)",
        "execution_status": "VARCHAR(32)",
        "current_node": "VARCHAR(128)",
        "current_step_id": "VARCHAR(128)",
        "current_step_sequence": "INTEGER NOT NULL DEFAULT 0",
        "last_event_sequence": "INTEGER NOT NULL DEFAULT 0",
        "generation_attempt": "INTEGER NOT NULL DEFAULT 1",
        "revision_count": "INTEGER NOT NULL DEFAULT 0",
        "retrieval_status": "VARCHAR(32)",
        "final_decision": "VARCHAR(256)",
        "last_error_code": "VARCHAR(128)",
        "replay_completeness": "VARCHAR(32) NOT NULL DEFAULT 'legacy_partial'",
        "owner_instance_id": "VARCHAR(128)",
        "lease_expires_at": "DATETIME",
        "heartbeat_at": "DATETIME",
        "row_version": "INTEGER NOT NULL DEFAULT 1",
        "updated_at": "DATETIME",
    },
    "agent_steps": {
        "schema_version": "VARCHAR(16) NOT NULL DEFAULT '1.0'",
        "node_name": "VARCHAR(128)",
        "input_summary": "TEXT",
        "output_summary": "TEXT",
        "resource_ids": "JSON DEFAULT '[]'",
        "review_ids": "JSON DEFAULT '[]'",
        "generation_attempt": "INTEGER NOT NULL DEFAULT 1",
        "error_code": "VARCHAR(128)",
        "llm_call_id": "VARCHAR(128)",
        "model_name": "VARCHAR(128)",
        "provider_request_id": "VARCHAR(256)",
        "structured_output_mode": "VARCHAR(32)",
        "finish_reason": "VARCHAR(64)",
        "input_tokens": "INTEGER",
        "output_tokens": "INTEGER",
        "total_tokens": "INTEGER",
        "llm_duration_ms": "INTEGER",
        "llm_attempts": "JSON DEFAULT '[]'",
        "retrieval_status": "VARCHAR(32)",
        "retrieval_config_hash": "VARCHAR(64)",
        "retrieval_query_hashes": "JSON DEFAULT '[]'",
        "retrieval_candidate_count": "INTEGER",
        "retrieval_dropped_candidate_count": "INTEGER",
        "retrieval_partial_failure_count": "INTEGER",
        "payload_hash": "VARCHAR(64)",
    },
    "generated_resources": {
        "run_id": "VARCHAR(128)",
        "generation_step_id": "VARCHAR(128)",
    },
}


POSTGRES_COLUMNS: dict[str, dict[str, str]] = {
    table: {
        column: ddl.replace("DATETIME", "TIMESTAMP WITH TIME ZONE")
        for column, ddl in columns.items()
    }
    for table, columns in SQLITE_COLUMNS.items()
}


def _add_missing_columns(engine: Engine) -> None:
    backend = engine.url.get_backend_name()
    definitions = POSTGRES_COLUMNS if backend == "postgresql" else SQLITE_COLUMNS
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    existing_by_table = {
        table: {item["name"] for item in inspector.get_columns(table)}
        for table in definitions
        if table in tables
    }
    with engine.begin() as connection:
        for table, columns in definitions.items():
            if table not in tables:
                continue
            existing = existing_by_table[table]
            for column, ddl in columns.items():
                if column not in existing:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        if "agent_steps" in tables:
            connection.execute(
                text("UPDATE agent_steps SET node_name = agent_name WHERE node_name IS NULL")
            )
        if "agent_runs" in tables:
            connection.execute(
                text("UPDATE agent_runs SET updated_at = CURRENT_TIMESTAMP WHERE updated_at IS NULL")
            )


def _create_indexes(engine: Engine) -> None:
    statements = (
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_request_hash ON agent_runs (request_hash)",
        "CREATE INDEX IF NOT EXISTS ix_agent_runs_lease_expires_at ON agent_runs (lease_expires_at)",
        "CREATE INDEX IF NOT EXISTS ix_generated_resources_run_id ON generated_resources (run_id)",
        "CREATE INDEX IF NOT EXISTS ix_generated_resources_generation_step_id ON generated_resources (generation_step_id)",
    )
    tables = set(inspect(engine).get_table_names())
    with engine.begin() as connection:
        for statement in statements:
            table = statement.rsplit(" ON ", 1)[1].split(" ", 1)[0]
            if table in tables:
                connection.execute(text(statement))


def apply_p0_04_migration(engine: Engine) -> None:
    """Apply the idempotent P0-04 migration after metadata table creation."""

    with engine.begin() as connection:
        already_applied = connection.execute(
            text(
                "SELECT migration_id FROM schema_migrations "
                "WHERE migration_id = :migration_id"
            ),
            {"migration_id": MIGRATION_ID},
        ).first()
    _add_missing_columns(engine)
    _create_indexes(engine)
    if not already_applied:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"
                ),
                {"migration_id": MIGRATION_ID},
            )
