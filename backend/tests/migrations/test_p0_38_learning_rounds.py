"""Additive round migration, durable triggers and guarded physical rollback."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.feedback.round_models import ROUND_MODELS
from app.db.migrations.p0_38_learning_rounds import (
    apply_p0_38_learning_rounds_migration as apply,
    rollback_p0_38_learning_rounds_migration as rollback,
)
from app.db.shared.models import Base


def test_old_schema_upgrade_installs_round_tables_and_watermarks_idempotently(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'round.db'}")
    names = {model.__tablename__ for model in ROUND_MODELS}
    Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items() if name not in names])
    assert not names.intersection(inspect(engine).get_table_names())
    apply(engine)
    assert names <= set(inspect(engine).get_table_names())
    with engine.begin() as db:
        identity = db.execute(text("SELECT installation_id FROM report_read_watermarks")).scalar_one()
        for name in names:
            installed = db.execute(text("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND name LIKE :prefix"),
                                   {"prefix": f"trg_report_{name}_%"}).scalar_one()
            assert installed == 3
    apply(engine)
    with engine.connect() as db:
        assert db.execute(text("SELECT installation_id FROM report_read_watermarks")).scalar_one() == identity
    rollback(engine)
    assert not names.intersection(inspect(engine).get_table_names())
    engine.dispose()


def test_rollback_refuses_new_business_facts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'round-facts.db'}")
    Base.metadata.create_all(engine)
    apply(engine)
    with engine.begin() as db:
        db.execute(text("INSERT INTO learning_rounds (round_id,learner_id,knowledge_base_id,protocol_version,selection_key,selection_hash,budget_snapshot,created_at,row_version) VALUES ('r','l','kb','learning-round/v1','key','hash','{}',CURRENT_TIMESTAMP,1)"))
    with pytest.raises(ValueError, match="ROUND_ROLLBACK_HAS_FACTS"):
        rollback(engine)
    assert "learning_rounds" in inspect(engine).get_table_names()
    engine.dispose()


def test_grading_lease_heartbeat_does_not_invalidate_report_content(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'lease-watermark.db'}")
    Base.metadata.create_all(engine)
    apply(engine)
    with engine.begin() as db:
        db.execute(text("INSERT INTO learning_round_evaluation_sessions (session_id,stage_id,manifest_hash,manifest,created_at,grading_state,grading_generation,row_version) VALUES ('s','stage','hash','{}',CURRENT_TIMESTAMP,'idle',0,1)"))
        before = db.execute(text("SELECT epoch FROM report_read_watermarks")).scalar_one()
        db.execute(text("UPDATE learning_round_evaluation_sessions SET grading_owner='new-owner',grading_lease_expires_at=CURRENT_TIMESTAMP,grading_generation=1,row_version=2"))
        assert db.execute(text("SELECT epoch FROM report_read_watermarks")).scalar_one() == before
        db.execute(text("UPDATE learning_round_evaluation_sessions SET grading_state='grading'"))
        assert db.execute(text("SELECT epoch FROM report_read_watermarks")).scalar_one() == before + 1
    engine.dispose()
