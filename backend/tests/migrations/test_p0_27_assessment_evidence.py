from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_27_assessment_evidence import apply_p0_27_assessment_evidence_migration


def test_assessment_metadata_column_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE ability_state_events (event_id TEXT PRIMARY KEY, occurred_at TIMESTAMP NOT NULL)"
        ))
        connection.execute(text(
            "CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY)"
        ))

    apply_p0_27_assessment_evidence_migration(engine)
    apply_p0_27_assessment_evidence_migration(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("ability_state_events")}
    assert "evidence_metadata" in columns
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM schema_migrations WHERE migration_id='20260826_p0_27_assessment_evidence'"
        )).scalar_one() == 1
