from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_25_practice_guide_json import MIGRATION_ID, apply_p0_25_practice_guide_json_migration


def test_practice_guide_json_migration_is_additive_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'practice-guide.sqlite'}")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE generated_resources (resource_id VARCHAR(64) PRIMARY KEY)")

    apply_p0_25_practice_guide_json_migration(engine)
    apply_p0_25_practice_guide_json_migration(engine)

    assert {item["name"] for item in inspect(engine).get_columns("generated_resources")} >= {
        "practice_guide_payload", "practice_guide_payload_hash",
    }
    with engine.connect() as db:
        assert db.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).scalar_one() == 1
