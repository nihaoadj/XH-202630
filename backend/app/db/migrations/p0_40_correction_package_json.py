"""Add nullable canonical correction package storage; old rows remain unchanged."""
from sqlalchemy import inspect, text

MIGRATION_ID = "20261109_p0_40_correction_package_json"


def apply_p0_40_correction_package_json_migration(engine):
    with engine.begin() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        if "generated_resources" not in tables:
            return
        columns = {c["name"] for c in inspector.get_columns("generated_resources")}
        for name, kind in (("correction_package_payload", "JSON"), ("correction_package_payload_hash", "VARCHAR(64)")):
            if name not in columns:
                connection.execute(text(f"ALTER TABLE generated_resources ADD COLUMN {name} {kind}"))
        if "schema_migrations" in tables and not connection.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).first():
            connection.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})
