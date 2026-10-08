"""Additive storage for node-scoped evidence and V2 review practice payloads."""
from __future__ import annotations
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260825_p0_22_review_practice"

def apply_p0_22_review_practice_migration(engine: Engine) -> None:
    inspector = inspect(engine); tables = set(inspector.get_table_names())
    with engine.begin() as connection:
        if "generated_resources" in tables:
            columns = {item["name"] for item in inspector.get_columns("generated_resources")}
            if "review_practice_payload" not in columns: connection.execute(text("ALTER TABLE generated_resources ADD COLUMN review_practice_payload JSON"))
            if "review_practice_payload_hash" not in columns: connection.execute(text("ALTER TABLE generated_resources ADD COLUMN review_practice_payload_hash VARCHAR(64)"))
        if "resource_specs" in tables:
            columns = {item["name"] for item in inspector.get_columns("resource_specs")}
            if "node_evidence_map" not in columns: connection.execute(text("ALTER TABLE resource_specs ADD COLUMN node_evidence_map JSON"))
        if "schema_migrations" in tables and not connection.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).first():
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})

__all__ = ["apply_p0_22_review_practice_migration"]
