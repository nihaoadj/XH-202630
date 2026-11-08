import pytest
from sqlalchemy import create_engine, text, event
from app.db.migrations.p0_36_claim_extraction import apply_p0_36_claim_extraction_migration as old_apply
from app.db.migrations.p0_37_claim_estimate import apply_p0_37_claim_estimate_migration as apply, rollback_p0_37_claim_estimate_migration as rollback


def old_database(tmp_path):
    engine=create_engine(f"sqlite:///{tmp_path/'upgrade.db'}")
    with engine.begin() as db:
        db.exec_driver_sql('PRAGMA foreign_keys=ON')
        db.exec_driver_sql('CREATE TABLE agent_runs(run_id VARCHAR(128) PRIMARY KEY, input_payload JSON)')
        db.exec_driver_sql('CREATE INDEX keep_payload ON agent_runs(input_payload)')
        db.exec_driver_sql('CREATE TABLE child(id TEXT PRIMARY KEY, run_id TEXT REFERENCES agent_runs(run_id) ON DELETE CASCADE)')
    old_apply(engine)
    with engine.begin() as db:
        db.exec_driver_sql("INSERT INTO agent_runs(run_id,input_payload,claim_extraction_mode) VALUES ('old','{}','neutral_batch_v1')")
        db.exec_driver_sql("INSERT INTO child VALUES ('c','old')")
    return engine


def test_preserves_rows_constraints_fk_indexes_repeat_start_and_rollback(tmp_path):
    engine=old_database(tmp_path)
    apply(engine);old_apply(engine);apply(engine)
    with engine.begin() as db:
        assert db.exec_driver_sql("SELECT claim_extraction_mode FROM agent_runs WHERE run_id='old'").scalar_one()=='neutral_batch_v1'
        assert db.exec_driver_sql('SELECT * FROM child').all()==[('c','old')]
        assert 'keep_payload' in {row[1] for row in db.exec_driver_sql('PRAGMA index_list(agent_runs)')}
        assert not db.exec_driver_sql('PRAGMA foreign_key_check').all()
        db.exec_driver_sql("INSERT INTO agent_runs(run_id,input_payload,claim_extraction_mode) VALUES ('new','{}','neutral_estimate_v1')")
        with pytest.raises(Exception,match='immutable'):
            db.exec_driver_sql("UPDATE agent_runs SET claim_extraction_mode='legacy_v3' WHERE run_id='new'")
        with pytest.raises(Exception):
            db.exec_driver_sql("INSERT INTO agent_runs(run_id,claim_extraction_mode) VALUES ('invalid','unknown')")
    with pytest.raises(ValueError,match='estimate'):
        rollback(engine)
    with engine.begin() as db:
        db.exec_driver_sql("DELETE FROM agent_runs WHERE run_id='new'")
    rollback(engine);rollback(engine)
    with engine.begin() as db:
        assert db.exec_driver_sql("SELECT claim_extraction_mode FROM agent_runs WHERE run_id='old'").scalar_one()=='neutral_batch_v1'
        with pytest.raises(Exception):
            db.exec_driver_sql("INSERT INTO agent_runs(run_id,claim_extraction_mode) VALUES ('new','neutral_estimate_v1')")


def test_failure_rolls_back_column_and_trigger_changes(tmp_path):
    engine=old_database(tmp_path)
    with engine.connect() as db:
        before=db.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='agent_runs'").scalar_one()
    def fail(conn,cursor,statement,params,context,executemany):
        if statement.startswith('CREATE TRIGGER trg_claim_extraction_mode_immutable'):
            raise RuntimeError('injected migration interruption')
    event.listen(engine,'before_cursor_execute',fail)
    with pytest.raises(RuntimeError):
        apply(engine)
    event.remove(engine,'before_cursor_execute',fail)
    with engine.begin() as db:
        assert db.exec_driver_sql("SELECT sql FROM sqlite_master WHERE name='agent_runs'").scalar_one()==before
        assert db.exec_driver_sql("SELECT claim_extraction_mode FROM agent_runs WHERE run_id='old'").scalar_one()=='neutral_batch_v1'
        assert not db.exec_driver_sql('PRAGMA foreign_key_check').all()
        with pytest.raises(Exception,match='immutable'):
            db.exec_driver_sql("UPDATE agent_runs SET claim_extraction_mode='legacy_v3'")
    apply(engine)


def test_modern_orm_and_optional_non_sqlite(tmp_path):
    from types import SimpleNamespace
    from app.db.shared.models import Base
    engine=create_engine(f"sqlite:///{tmp_path/'modern.db'}")
    Base.metadata.create_all(engine);old_apply(engine);apply(engine);apply(engine)
    apply(SimpleNamespace(dialect=SimpleNamespace(name='postgresql')))
    rollback(SimpleNamespace(dialect=SimpleNamespace(name='postgresql')))
