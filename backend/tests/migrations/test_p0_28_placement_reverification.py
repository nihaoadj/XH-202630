from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_28_placement_reverification import apply_p0_28_placement_reverification_migration


def test_placement_reverification_column_is_additive_and_idempotent():
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE learner_curriculum_nodes (curriculum_node_id TEXT PRIMARY KEY)"
        ))
        connection.execute(text(
            "CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY)"
        ))

    apply_p0_28_placement_reverification_migration(engine)
    apply_p0_28_placement_reverification_migration(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("learner_curriculum_nodes")}
    assert "placement_verification_required" in columns
    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM schema_migrations "
            "WHERE migration_id='20260826_p0_28_placement_reverification'"
        )).scalar_one() == 1
