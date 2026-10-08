from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_06 import MIGRATION_ID, apply_p0_06_migration


def test_p0_06_sqlite_migration_is_additive_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p0_06.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY, applied_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE agent_runs (run_id VARCHAR(128) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE generated_resources (resource_id VARCHAR(64) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE resource_reviews (review_id VARCHAR(128) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE retrieval_evidence_snapshots (evidence_id VARCHAR(128) PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE resource_claims ("
            "claim_id VARCHAR(128) PRIMARY KEY, review_id VARCHAR(128) NOT NULL, "
            "resource_id VARCHAR(64) NOT NULL, claim_text TEXT NOT NULL, supported BOOLEAN NOT NULL)"
        ))

    apply_p0_06_migration(engine)
    apply_p0_06_migration(engine)

    inspector = inspect(engine)
    assert {"claim_judgements", "claim_evidence"} <= set(inspector.get_table_names())
    claim_columns = {item["name"] for item in inspector.get_columns("resource_claims")}
    assert {
        "schema_version",
        "run_id",
        "resource_version",
        "claim_index",
        "claim_type",
        "source_text_hash",
        "claim_hash",
    } <= claim_columns
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
