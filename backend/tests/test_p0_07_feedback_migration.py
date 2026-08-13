from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_07_feedback import MIGRATION_ID, apply_p0_07_feedback_migration


def test_feedback_closed_loop_migration_is_additive_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'feedback-p0-07.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE learner_profiles (learner_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE knowledge_states (state_id VARCHAR(128) PRIMARY KEY, learner_id VARCHAR(64), "
            "knowledge_base_id VARCHAR(128), skill_node_id VARCHAR(128))"
        ))
        connection.execute(text("CREATE TABLE generated_resources (resource_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE agent_runs (run_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE generation_jobs (run_id VARCHAR(128) PRIMARY KEY)"))

    apply_p0_07_feedback_migration(engine)
    apply_p0_07_feedback_migration(engine)

    inspector = inspect(engine)
    assert {"profile_version"} <= {item["name"] for item in inspector.get_columns("learner_profiles")}
    assert {"attempt_count", "last_attempt_id", "row_version"} <= {
        item["name"] for item in inspector.get_columns("knowledge_states")
    }
    assert {
        "learning_attempts",
        "learning_attempt_point_results",
        "feedback_decisions",
        "knowledge_state_mutations",
        "learner_profile_versions",
        "learning_paths",
        "learning_path_nodes",
        "learning_path_mutations",
        "feedback_followup_runs",
    } <= set(inspector.get_table_names())
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
