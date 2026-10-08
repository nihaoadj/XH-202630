"""Additive storage for the canonical structured practice-guide payload."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260825_p0_25_practice_guide_json"


def apply_p0_25_practice_guide_json_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    with engine.begin() as connection:
        if "generated_resources" in set(inspector.get_table_names()):
            columns = {item["name"] for item in inspector.get_columns("generated_resources")}
            if "practice_guide_payload" not in columns:
                connection.execute(text("ALTER TABLE generated_resources ADD COLUMN practice_guide_payload JSON"))
            if "practice_guide_payload_hash" not in columns:
                connection.execute(text("ALTER TABLE generated_resources ADD COLUMN practice_guide_payload_hash VARCHAR(64)"))
        if "schema_migrations" in set(inspector.get_table_names()) and not connection.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
        ).first():
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})


__all__ = ["apply_p0_25_practice_guide_json_migration"]
