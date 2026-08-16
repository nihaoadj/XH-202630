"""P0-06 additive Claim/Evidence audit migration."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.models import ClaimEvidenceORM, ClaimJudgementORM


MIGRATION_ID = "20260809_p0_06_claim_evidence_audit"

ADDITIVE_COLUMNS = {
    "generated_resources": {
        "legacy_reviewer_score": "FLOAT",
        "claim_hallucination_rate": "FLOAT",
        "claim_metric_status": "VARCHAR(32)",
    },
    "resource_reviews": {
        "legacy_reviewer_score": "FLOAT",
        "claim_hallucination_rate": "FLOAT",
        "claim_metric_status": "VARCHAR(32)",
    },
    "resource_claims": {
        "schema_version": "VARCHAR(16)",
        "run_id": "VARCHAR(128)",
        "resource_version": "INTEGER",
        "claim_index": "INTEGER",
        "claim_type": "VARCHAR(32)",
        "knowledge_point_id": "VARCHAR(256)",
        "source_text": "TEXT",
        "source_start": "INTEGER",
        "source_end": "INTEGER",
        "source_text_hash": "VARCHAR(64)",
        "extraction_method": "VARCHAR(32)",
        "extractor_model": "VARCHAR(256)",
        "extractor_prompt_version": "VARCHAR(64)",
        "claim_hash": "VARCHAR(64)",
    },
}


def apply_p0_06_migration(engine: Engine) -> None:
    # create_all normally creates these tables; explicit checkfirst also supports
    # callers that execute migrations against an existing P0-05 database.
    ClaimJudgementORM.__table__.create(bind=engine, checkfirst=True)
    ClaimEvidenceORM.__table__.create(bind=engine, checkfirst=True)
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    existing = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ADDITIVE_COLUMNS
        if table in tables
    }
    with engine.begin() as connection:
        for table, columns in ADDITIVE_COLUMNS.items():
            if table not in tables:
                continue
            for column, ddl in columns.items():
                if column not in existing[table]:
                    connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        if "resource_claims" in tables:
            connection.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_resource_claims_run_version "
                "ON resource_claims (run_id, resource_id, resource_version, claim_index)"
            ))
        if "schema_migrations" in tables:
            row = connection.execute(
                text("SELECT migration_id FROM schema_migrations WHERE migration_id=:migration_id"),
                {"migration_id": MIGRATION_ID},
            ).first()
            if not row:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
