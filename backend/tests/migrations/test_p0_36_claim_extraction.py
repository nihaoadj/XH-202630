import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_36_claim_extraction import (
    apply_p0_36_claim_extraction_migration as apply,
    rollback_p0_36_claim_extraction_migration as rollback,
)


def test_optional_non_sqlite_initialization_keeps_existing_skip_contract():
    from types import SimpleNamespace
    engine = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
    apply(engine)
    rollback(engine)


def test_old_database_additive_idempotent_immutable_and_empty_rollback(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as db:
        db.execute(text("PRAGMA foreign_keys=ON"))
        db.execute(text("CREATE TABLE agent_runs (run_id VARCHAR(128) PRIMARY KEY, input_payload JSON)"))
        db.execute(text("INSERT INTO agent_runs VALUES ('old', :payload)"), {"payload": '{"legacy":true}'})
    apply(engine)
    apply(engine)
    with engine.begin() as db:
        row = db.execute(text("SELECT * FROM agent_runs")).mappings().one()
        assert row["claim_extraction_mode"] == "legacy_v3" and row["input_payload"] == '{"legacy":true}'
        assert db.execute(text("SELECT COUNT(*) FROM claim_extraction_runs")).scalar_one() == 0
        with pytest.raises(Exception, match="immutable"):
            db.execute(text("UPDATE agent_runs SET claim_extraction_mode='neutral_batch_v1'"))
    rollback(engine)
    assert "claim_extraction_runs" not in inspect(engine).get_table_names()
    assert "claim_extraction_mode" not in {c["name"] for c in inspect(engine).get_columns("agent_runs")}
    apply(engine)
    with engine.begin() as db:
        db.execute(text("INSERT INTO agent_runs VALUES ('neutral', '{}', 'neutral_batch_v1')"))
    with pytest.raises(ValueError, match="neutral"):
        rollback(engine)
    with engine.begin() as db:
        db.execute(text("INSERT INTO claim_extraction_runs (run_id,schema_version,policy_hash,policy_json,revision,state_hash,state_json) VALUES ('neutral','1.0','x','{}',0,'y','{}')"))
    with pytest.raises(ValueError, match="nonempty"):
        rollback(engine)
    with engine.begin() as db:
        db.execute(text("DELETE FROM agent_runs WHERE run_id='neutral'"))
        assert db.execute(text("SELECT COUNT(*) FROM claim_extraction_runs")).scalar_one() == 0
    engine.dispose()
