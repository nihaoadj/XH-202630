from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_04 import MIGRATION_ID, apply_p0_04_migration
from app.db.models import Base


def test_p0_04_sqlite_migration_is_additive_and_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE agent_runs (
                run_id VARCHAR(128) PRIMARY KEY,
                learner_id VARCHAR(64),
                knowledge_base_id VARCHAR(128),
                topic VARCHAR(512),
                status VARCHAR(32) NOT NULL,
                input_payload JSON,
                output_payload JSON,
                started_at DATETIME,
                ended_at DATETIME
            )
        """))
        connection.execute(text("""
            CREATE TABLE agent_steps (
                step_id VARCHAR(128) PRIMARY KEY,
                run_id VARCHAR(128) NOT NULL,
                step_no INTEGER NOT NULL,
                agent_name VARCHAR(128) NOT NULL,
                action VARCHAR(256) NOT NULL,
                status VARCHAR(32) NOT NULL,
                input_payload JSON,
                output_payload JSON,
                decision_reason TEXT,
                evidence_refs JSON,
                retry_count INTEGER,
                error_message TEXT,
                started_at DATETIME,
                ended_at DATETIME,
                duration_ms INTEGER
            )
        """))
        connection.execute(text("""
            CREATE TABLE generated_resources (
                resource_id VARCHAR(64) PRIMARY KEY,
                learner_id VARCHAR(64) NOT NULL,
                topic VARCHAR(256) NOT NULL,
                resource_type VARCHAR(32) NOT NULL,
                difficulty VARCHAR(16) NOT NULL,
                storage_type VARCHAR(16) NOT NULL
            )
        """))
        connection.execute(
            text("""
                INSERT INTO agent_runs
                (run_id, status, input_payload, output_payload)
                VALUES ('legacy-run', 'completed', '{}', '{}')
            """)
        )
    Base.metadata.create_all(engine)
    apply_p0_04_migration(engine)
    apply_p0_04_migration(engine)

    inspector = inspect(engine)
    run_columns = {item["name"] for item in inspector.get_columns("agent_runs")}
    step_columns = {item["name"] for item in inspector.get_columns("agent_steps")}
    resource_columns = {item["name"] for item in inspector.get_columns("generated_resources")}
    assert {"request_hash", "last_event_sequence", "replay_completeness"} <= run_columns
    assert {"node_name", "llm_attempts", "payload_hash"} <= step_columns
    assert {"run_id", "generation_step_id"} <= resource_columns
    resource_indexes = {item["name"] for item in inspector.get_indexes("generated_resources")}
    assert "ix_generated_resources_run_id" in resource_indexes
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM agent_runs")).scalar_one() == 1
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
