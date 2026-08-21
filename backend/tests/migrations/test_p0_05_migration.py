from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_05 import MIGRATION_ID, apply_p0_05_migration


def test_p0_05_sqlite_migration_is_additive_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p0_05.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY, applied_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE generated_resources ("
            "resource_id VARCHAR(64) PRIMARY KEY, learner_id VARCHAR(64) NOT NULL, "
            "run_id VARCHAR(128), resource_type VARCHAR(32), version INTEGER, created_at DATETIME)"
        ))
        connection.execute(text(
            "CREATE TABLE resource_reviews (review_id VARCHAR(128) PRIMARY KEY)"
        ))
    apply_p0_05_migration(engine)
    apply_p0_05_migration(engine)
    inspector = inspect(engine)
    resource_columns = {item["name"] for item in inspector.get_columns("generated_resources")}
    review_columns = {item["name"] for item in inspector.get_columns("resource_reviews")}
    assert {"publication_status", "published_at"} <= resource_columns
    assert {"revision_instructions", "review_hash"} <= review_columns
    with engine.begin() as connection:
        count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id = :migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one()
    assert count == 1
