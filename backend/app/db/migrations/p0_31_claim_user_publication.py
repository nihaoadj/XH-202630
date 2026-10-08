"""Add Claim user publication decision fields to existing SQLite databases."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260827_p0_31_claim_user_publication"

def apply_p0_31_claim_user_publication_migration(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    with engine.begin() as conn:
        tables = set(inspect(engine).get_table_names())
        if "generated_resources" not in tables:
            return
        existing = {row[1] for row in conn.execute(text("PRAGMA table_info(generated_resources)"))}
        additions = {
            "claim_factual_pass_rate": "FLOAT",
            "claim_warning_publish": "BOOLEAN NOT NULL DEFAULT 0",
            "claim_publish_decision_pending": "BOOLEAN NOT NULL DEFAULT 0",
            "claim_publish_decision": "VARCHAR(32)",
        }
        for column, ddl in additions.items():
            if column not in existing:
                conn.execute(text(f"ALTER TABLE generated_resources ADD COLUMN {column} {ddl}"))
        if "schema_migrations" in tables and not conn.execute(
            text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}
        ).first():
            conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})

__all__ = ["MIGRATION_ID", "apply_p0_31_claim_user_publication_migration"]
