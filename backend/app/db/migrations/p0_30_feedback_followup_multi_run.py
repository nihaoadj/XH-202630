"""Allow one feedback attempt to own multiple independently audited runs."""
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

MIGRATION_ID = "20260826_p0_30_feedback_followup_multi_run"

def apply_p0_30_feedback_followup_multi_run_migration(engine: Engine) -> None:
    if engine.url.get_backend_name() != "sqlite":
        return
    tables = set(inspect(engine).get_table_names())
    if "feedback_followup_runs" not in tables:
        return
    with engine.begin() as conn:
        if "schema_migrations" in tables and conn.execute(text("SELECT 1 FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).first():
            return
        # A prior interrupted/partially-applied run may have created the new
        # table but not recorded the marker.  Do not rename the source table a
        # second time; just reconcile the marker and let startup continue.
        if "feedback_followup_runs_legacy" in tables and "feedback_followup_runs" in tables:
            if "schema_migrations" in tables:
                conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})
            return
        conn.execute(text("ALTER TABLE feedback_followup_runs RENAME TO feedback_followup_runs_legacy"))
        conn.execute(text("""CREATE TABLE feedback_followup_runs (
            relation_id VARCHAR(128) PRIMARY KEY,
            attempt_id VARCHAR(128) NOT NULL REFERENCES learning_attempts(attempt_id),
            decision_id VARCHAR(128) NOT NULL REFERENCES feedback_decisions(decision_id),
            parent_run_id VARCHAR(128) REFERENCES agent_runs(run_id),
            child_run_id VARCHAR(128) REFERENCES generation_jobs(run_id) UNIQUE,
            trigger_type VARCHAR(32) NOT NULL,
            status VARCHAR(32) NOT NULL,
            error_code VARCHAR(128),
            relation_type VARCHAR(32) NOT NULL DEFAULT 'selection',
            source_relation_id VARCHAR(128),
            source_child_run_id VARCHAR(128),
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
        )"""))
        conn.execute(text("""INSERT INTO feedback_followup_runs
            (relation_id,attempt_id,decision_id,parent_run_id,child_run_id,trigger_type,status,error_code,relation_type,created_at,updated_at)
            SELECT relation_id,attempt_id,decision_id,parent_run_id,child_run_id,trigger_type,status,error_code,'selection',created_at,updated_at
            FROM feedback_followup_runs_legacy"""))
        conn.execute(text("CREATE INDEX ix_feedback_followup_runs_attempt_id ON feedback_followup_runs(attempt_id)"))
        conn.execute(text("CREATE INDEX ix_feedback_followup_runs_relation_type ON feedback_followup_runs(relation_type)"))
        if "schema_migrations" in tables:
            conn.execute(text("INSERT INTO schema_migrations (migration_id) VALUES (:id)"), {"id": MIGRATION_ID})

__all__ = ["MIGRATION_ID", "apply_p0_30_feedback_followup_multi_run_migration"]
