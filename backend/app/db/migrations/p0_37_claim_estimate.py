"""Expand private run modes atomically without rebuilding referenced run rows."""
from uuid import uuid4
from sqlalchemy import inspect

MODES = "'legacy_v3', 'neutral_batch_v1', 'neutral_estimate_v1'"
OLD_MODES = "'legacy_v3', 'neutral_batch_v1'"


def _replace_mode(engine, *, rollback=False):
    if engine.dialect.name != "sqlite":
        return
    with engine.connect() as db:
        if "agent_runs" not in inspect(db).get_table_names():
            return
        if "claim_extraction_mode" not in {c["name"] for c in inspect(db).get_columns("agent_runs")}:
            return
        db.commit()
        db.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            if rollback:
                if db.exec_driver_sql("SELECT COUNT(*) FROM agent_runs WHERE claim_extraction_mode='neutral_estimate_v1'").scalar_one():
                    raise ValueError("cannot roll back estimate runs")
                if "claim_extraction_runs" in inspect(db).get_table_names() and db.exec_driver_sql(
                        "SELECT COUNT(*) FROM claim_extraction_runs WHERE schema_version='2.0'").scalar_one():
                    raise ValueError("cannot roll back estimate ledger")
            sql = db.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='table' AND name='agent_runs'").scalar_one()
            trigger = db.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='trigger' AND name='trg_claim_extraction_mode_valid'").scalar_one_or_none() or ""
            desired = OLD_MODES if rollback else MODES
            already = ("neutral_estimate_v1" not in sql and "neutral_estimate_v1" not in trigger) if rollback else ("neutral_estimate_v1" in sql and "neutral_estimate_v1" in trigger)
            if already:
                db.commit()
                return
            saved = db.exec_driver_sql("SELECT run_id,claim_extraction_mode FROM agent_runs ORDER BY run_id").all()
            temp = "claim_modes_" + uuid4().hex
            db.exec_driver_sql(f"CREATE TEMP TABLE {temp} AS SELECT run_id,claim_extraction_mode FROM agent_runs")
            db.exec_driver_sql("DROP TRIGGER IF EXISTS trg_claim_extraction_mode_valid")
            db.exec_driver_sql("DROP TRIGGER IF EXISTS trg_claim_extraction_mode_immutable")
            db.exec_driver_sql("ALTER TABLE agent_runs DROP COLUMN claim_extraction_mode")
            db.exec_driver_sql(f"ALTER TABLE agent_runs ADD COLUMN claim_extraction_mode VARCHAR(32) NOT NULL DEFAULT 'legacy_v3' CHECK (claim_extraction_mode IN ({desired}))")
            db.exec_driver_sql(f"UPDATE agent_runs SET claim_extraction_mode=(SELECT claim_extraction_mode FROM {temp} WHERE {temp}.run_id=agent_runs.run_id)")
            restored = db.exec_driver_sql("SELECT run_id,claim_extraction_mode FROM agent_runs ORDER BY run_id").all()
            if restored != saved:
                raise ValueError("mode migration changed run identities or modes")
            db.exec_driver_sql("CREATE TRIGGER trg_claim_extraction_mode_immutable BEFORE UPDATE OF claim_extraction_mode ON agent_runs WHEN NEW.claim_extraction_mode != OLD.claim_extraction_mode BEGIN SELECT RAISE(ABORT, 'immutable claim extraction mode'); END")
            db.exec_driver_sql(f"CREATE TRIGGER trg_claim_extraction_mode_valid BEFORE INSERT ON agent_runs WHEN NEW.claim_extraction_mode NOT IN ({desired}) BEGIN SELECT RAISE(ABORT, 'invalid claim extraction mode'); END")
            if db.exec_driver_sql("PRAGMA foreign_key_check").fetchall():
                raise ValueError("mode migration foreign key check failed")
            db.exec_driver_sql(f"DROP TABLE {temp}")
            db.commit()
        except BaseException:
            db.rollback()
            raise


def apply_p0_37_claim_estimate_migration(engine):
    _replace_mode(engine)


def rollback_p0_37_claim_estimate_migration(engine):
    _replace_mode(engine, rollback=True)
