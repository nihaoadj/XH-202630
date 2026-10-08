from sqlalchemy import create_engine, text

from app.db.migrations.p0_32_review_status import (
    MIGRATION_ID,
    apply_p0_32_review_status_migration,
)


def test_review_status_migration_normalizes_legacy_values_and_is_idempotent():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE resource_reviews (review_id TEXT PRIMARY KEY, status TEXT)"))
        conn.execute(text("CREATE TABLE generated_resources (resource_id TEXT PRIMARY KEY, review_status TEXT)"))
        conn.execute(text("INSERT INTO resource_reviews VALUES ('approve', 'approve'), ('revise', 'revise')"))
        conn.execute(text("INSERT INTO generated_resources VALUES ('legacy', 'approve')"))

    apply_p0_32_review_status_migration(engine)
    apply_p0_32_review_status_migration(engine)

    with engine.begin() as conn:
        assert conn.execute(text("SELECT status FROM resource_reviews WHERE review_id='approve'")).scalar_one() == "approved"
        assert conn.execute(text("SELECT status FROM resource_reviews WHERE review_id='revise'")).scalar_one() == "revision_requested"
        assert conn.execute(text("SELECT review_status FROM generated_resources WHERE resource_id='legacy'")).scalar_one() == "approved"
        assert conn.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).scalar_one() == 1
