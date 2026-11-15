"""Add durable dispatch without assigning existing jobs to a new consumer."""
from sqlalchemy import inspect, text


def apply_p0_34_generation_dispatch_migration(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as connection:
        if "generation_jobs" not in inspect(connection).get_table_names():
            return
        columns = {column["name"] for column in inspect(connection).get_columns("generation_jobs")}
        additions = {
            "dispatch_mode": "VARCHAR(16) NOT NULL DEFAULT 'legacy'",
            "dispatch_snapshot": "JSON", "submission_hash": "VARCHAR(64)",
            "claim_owner": "VARCHAR(128)", "claim_epoch": "INTEGER NOT NULL DEFAULT 0",
            "claim_count": "INTEGER NOT NULL DEFAULT 0", "lease_expires_at": "DATETIME",
            "next_attempt_at": "DATETIME", "retry_of_run_id": "VARCHAR(128)",
        }
        for name, definition in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE generation_jobs ADD COLUMN {name} {definition}"))
        connection.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_generation_retry_of ON generation_jobs(retry_of_run_id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_generation_dispatch_claim ON generation_jobs(dispatch_mode, status, next_attempt_at, created_at, run_id)"))
