"""Additive round migration, durable triggers and guarded physical rollback."""

import pytest
from sqlalchemy import create_engine, inspect, text

from app.db.feedback.round_models import ROUND_MODELS
from app.db.migrations.p0_38_learning_rounds import (
    apply_p0_38_learning_rounds_migration as apply,
    rollback_p0_38_learning_rounds_migration as rollback,
)
from app.db.migrations.p0_41_round_retake import apply_p0_41_round_retake_migration
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


def test_retake_upgrade_preserves_session_and_budget_foreign_key(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'retake.db'}")
    session = "learning_round_evaluation_sessions"
    Base.metadata.create_all(engine, tables=[table for name, table in Base.metadata.tables.items() if name != session])
    with engine.begin() as db:
        db.exec_driver_sql(f"""CREATE TABLE {session} (
            session_id VARCHAR(128) PRIMARY KEY, stage_id VARCHAR(128) NOT NULL UNIQUE
                REFERENCES learning_round_stages(stage_id),
            manifest_hash VARCHAR(64) NOT NULL, manifest JSON NOT NULL, created_at DATETIME NOT NULL,
            attempt_id VARCHAR(128) UNIQUE REFERENCES learning_attempts(attempt_id),
            grading_state VARCHAR(16) NOT NULL, submission_key VARCHAR(128), submission_hash VARCHAR(64),
            grading_owner VARCHAR(128), grading_generation INTEGER NOT NULL,
            grading_lease_expires_at DATETIME, row_version INTEGER NOT NULL
        )""")
        db.exec_driver_sql("CREATE TABLE retake_test_budget (session_id TEXT REFERENCES learning_round_evaluation_sessions(session_id))")
        db.exec_driver_sql("INSERT INTO knowledge_bases (knowledge_base_id, name, version, created_at) VALUES ('kb', 'kb', '1', CURRENT_TIMESTAMP)")
        # Minimal parent identities for the fixture without relying on profile defaults.
        db.exec_driver_sql("INSERT INTO learner_profiles (learner_id, learner_type, education, major, knowledge_base_id, skill_level, learning_goal, profile_version, created_at) VALUES ('l','test','test','test','kb','初级','test',1,CURRENT_TIMESTAMP)")
        db.exec_driver_sql("INSERT INTO learning_rounds (round_id, learner_id, knowledge_base_id, protocol_version, selection_key, selection_hash, budget_snapshot, created_at, row_version) VALUES ('r','l','kb','learning-round/v1','key','hash','{}',CURRENT_TIMESTAMP,1)")
        db.exec_driver_sql("INSERT INTO learning_round_stages (stage_id, round_id, kind, ordinal, selection_key, selection_hash, state, budget_snapshot, budget_counters, created_at, row_version) VALUES ('stage','r','initial',0,'key','hash','awaiting_assessment','{}','{}',CURRENT_TIMESTAMP,1)")
        db.exec_driver_sql(f"INSERT INTO {session} (session_id,stage_id,manifest_hash,manifest,created_at,grading_state,grading_generation,row_version) VALUES ('original','stage','hash','{{}}',CURRENT_TIMESTAMP,'idle',0,1)")
        db.exec_driver_sql("INSERT INTO retake_test_budget VALUES ('original')")
    apply(engine)
    apply_p0_41_round_retake_migration(engine)
    apply_p0_41_round_retake_migration(engine)
    with engine.begin() as db:
        assert db.exec_driver_sql(f"SELECT session_id, ordinal FROM {session}").one() == ("original", 1)
        db.exec_driver_sql(f"INSERT INTO {session} (session_id,stage_id,ordinal,manifest_hash,manifest,created_at,grading_state,grading_generation,row_version) VALUES ('retake','stage',2,'hash','{{}}',CURRENT_TIMESTAMP,'idle',0,1)")
        assert db.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert db.exec_driver_sql("SELECT session_id FROM retake_test_budget").scalar_one() == "original"
        assert db.exec_driver_sql("SELECT COUNT(*) FROM sqlite_master WHERE type='trigger' AND tbl_name=?", (session,)).scalar_one() == 3
    engine.dispose()
