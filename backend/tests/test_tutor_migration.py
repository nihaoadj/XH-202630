from sqlalchemy import create_engine, inspect, text

from app.db.migrations.tutor import MIGRATION_ID, apply_tutor_migration


def test_tutor_migration_is_additive_idempotent_and_keeps_turn_guards(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tutor-migration.db'}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_migrations "
            "(migration_id VARCHAR(128) PRIMARY KEY)"
        ))

    apply_tutor_migration(engine)
    apply_tutor_migration(engine)

    inspector = inspect(engine)
    assert {"tutor_sessions", "tutor_turns"}.issubset(inspector.get_table_names())
    unique_columns = {
        tuple(item["column_names"])
        for item in inspector.get_unique_constraints("tutor_turns")
    }
    assert ("session_id", "sequence") in unique_columns
    assert ("session_id", "client_message_id") in unique_columns
    foreign_keys = {
        tuple(item["constrained_columns"]): item["referred_table"]
        for item in inspector.get_foreign_keys("tutor_turns")
    }
    assert foreign_keys[("session_id",)] == "tutor_sessions"
    with engine.begin() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM schema_migrations "
                "WHERE migration_id=:migration_id"
            ),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
