from sqlalchemy import create_engine, text

from app.db.migrations.p0_07 import apply_p0_07_migration


def test_p0_07_adds_runtime_observability_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE agent_steps (step_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))

    apply_p0_07_migration(engine)
    apply_p0_07_migration(engine)

    with engine.begin() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(agent_steps)")}
        migration_count = connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": "20260810_p0_07_runtime_observability"},
        ).scalar_one()
    assert {"retrieval_profile", "workflow_elapsed_ms", "workflow_remaining_ms"}.issubset(columns)
    assert migration_count == 1
