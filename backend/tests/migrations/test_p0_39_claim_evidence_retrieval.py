"""Additive T50 side tables: fresh install, idempotent upgrade, guarded rollback."""

from sqlalchemy import create_engine, inspect, text

from app.db.claim.supplement_models import SUPPLEMENT_MODELS, SUPPLEMENT_TABLES
from app.db.migrations.p0_39_claim_evidence_retrieval import (
    apply_p0_39_claim_evidence_retrieval_migration as apply,
    rollback_p0_39_claim_evidence_retrieval_migration as rollback,
)
from app.db.shared.models import Base


def _legacy_metadata_tables():
    return [
        table for name, table in Base.metadata.tables.items()
        if name not in SUPPLEMENT_TABLES
    ]


def test_upgrade_adds_only_the_new_tables_and_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't50.db'}")
    Base.metadata.create_all(engine, tables=_legacy_metadata_tables())
    before = set(inspect(engine).get_table_names())
    assert not set(SUPPLEMENT_TABLES) & before

    apply(engine)
    after = set(inspect(engine).get_table_names())
    assert set(SUPPLEMENT_TABLES) <= after
    assert before <= after

    apply(engine)
    with engine.connect() as db:
        assert set(SUPPLEMENT_TABLES) <= set(inspect(engine).get_table_names())
        count = db.execute(text("SELECT COUNT(*) FROM claim_evidence_retrieval_runs")).scalar_one()
        assert count == 0
    engine.dispose()


def test_rollback_removes_empty_tables_and_refuses_real_facts(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 't50-rollback.db'}")
    Base.metadata.create_all(engine)
    apply(engine)

    rollback(engine)
    assert not set(SUPPLEMENT_TABLES) & set(inspect(engine).get_table_names())

    apply(engine)
    with engine.begin() as db:
        db.execute(text(
            "INSERT INTO claim_evidence_retrieval_runs "
            "(run_id,schema_version,policy_hash,policy_json,revision,reserved_tokens,"
            "known_tokens,unknown_tokens,logical_calls,attempts,query_count,epoch,"
            "started_at,deadline_at,status) "
            "VALUES ('run-1','1.0','" + "a" * 64 + "','{}',0,0,0,0,0,0,0,0,"
            "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,'pending')"
        ))
    try:
        rollback(engine)
    except ValueError as exc:
        assert "ROLLBACK_HAS_FACTS" in str(exc)
    else:  # pragma: no cover - the guard must fail closed
        raise AssertionError("rollback must refuse existing facts")
    assert set(SUPPLEMENT_TABLES) <= set(inspect(engine).get_table_names())
    engine.dispose()


def test_model_metadata_is_registered_for_app_startup():
    names = {model.__tablename__ for model in SUPPLEMENT_MODELS}
    assert names == set(SUPPLEMENT_TABLES)
    assert names <= set(Base.metadata.tables)
