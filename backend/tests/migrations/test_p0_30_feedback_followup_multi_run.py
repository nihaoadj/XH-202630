from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_30_feedback_followup_multi_run import (
    MIGRATION_ID,
    apply_p0_30_feedback_followup_multi_run_migration,
)


def test_followup_migration_removes_attempt_singleton_and_preserves_rows(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'followups.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE learning_attempts (attempt_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE feedback_decisions (decision_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE agent_runs (run_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE generation_jobs (run_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("INSERT INTO learning_attempts VALUES ('a1')"))
        conn.execute(text("INSERT INTO feedback_decisions VALUES ('d1')"))
        conn.execute(text("INSERT INTO generation_jobs VALUES ('r1')"))
        conn.execute(text("""CREATE TABLE feedback_followup_runs (
            relation_id VARCHAR(128) PRIMARY KEY, attempt_id VARCHAR(128) NOT NULL,
            decision_id VARCHAR(128) NOT NULL, parent_run_id VARCHAR(128),
            child_run_id VARCHAR(128) UNIQUE, trigger_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL, error_code VARCHAR(128),
            created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL
        )"""))
        conn.execute(text("INSERT INTO feedback_followup_runs VALUES ('f1','a1','d1',NULL,'r1','selection','queued',NULL,'2026-01-01','2026-01-01')"))

    apply_p0_30_feedback_followup_multi_run_migration(engine)
    apply_p0_30_feedback_followup_multi_run_migration(engine)

    columns = {item["name"] for item in inspect(engine).get_columns("feedback_followup_runs")}
    assert {"relation_type", "source_relation_id", "source_child_run_id"} <= columns
    with engine.begin() as conn:
        assert conn.execute(text("SELECT COUNT(*) FROM feedback_followup_runs WHERE relation_id='f1' AND relation_type='selection'")).scalar_one() == 1
        conn.execute(text("INSERT INTO generation_jobs VALUES ('r2')"))
        conn.execute(text("""INSERT INTO feedback_followup_runs
            (relation_id,attempt_id,decision_id,parent_run_id,child_run_id,trigger_type,status,relation_type)
            VALUES ('f2','a1','d1',NULL,'r2','selection','queued','selection')"""))
        assert conn.execute(text("SELECT created_at IS NOT NULL AND updated_at IS NOT NULL FROM feedback_followup_runs WHERE relation_id='f2' ")).scalar_one() == 1
        assert conn.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).scalar_one() == 1


def test_followup_migration_accepts_current_schema_created_by_orm(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'current-followups.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        conn.execute(text("""CREATE TABLE feedback_followup_runs (
            relation_id VARCHAR(128) PRIMARY KEY, attempt_id VARCHAR(128) NOT NULL,
            decision_id VARCHAR(128) NOT NULL, parent_run_id VARCHAR(128),
            child_run_id VARCHAR(128) UNIQUE, trigger_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL, error_code VARCHAR(128),
            relation_type VARCHAR(32) NOT NULL DEFAULT 'selection',
            source_relation_id VARCHAR(128), source_child_run_id VARCHAR(128),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("CREATE INDEX ix_feedback_followup_runs_attempt_id ON feedback_followup_runs(attempt_id)"))
        conn.execute(text("CREATE INDEX ix_feedback_followup_runs_relation_type ON feedback_followup_runs(relation_type)"))

    apply_p0_30_feedback_followup_multi_run_migration(engine)

    with engine.begin() as conn:
        assert conn.execute(text(
            "SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"
        ), {"id": MIGRATION_ID}).scalar_one() == 1
        assert conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='index' "
            "AND name='ix_feedback_followup_runs_attempt_id'"
        )).scalar_one() == 1
