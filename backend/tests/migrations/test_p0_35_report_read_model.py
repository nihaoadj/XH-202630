from datetime import datetime, timezone

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration as apply, rollback_p0_35_report_read_model_migration as rollback
from app.db.reports.repository import SQLReportReadRepository
from app.db.reports.watermarks import INDEXES, TABLE, WATCHED_TABLES, expected_triggers, source_columns
from app.db.shared.models import Base


@pytest.fixture
def database(tmp_path):
    # This fixture tests trigger mechanics on the actual schema, independently
    # of FK/domain validation. Real report fixtures enable foreign keys.
    engine = create_engine(f"sqlite:///{tmp_path / 'watermarks.db'}")
    Base.metadata.create_all(engine)
    apply(engine)
    yield engine
    engine.dispose()


def _epoch(connection):
    return connection.execute(text(f'SELECT epoch FROM "{TABLE}" WHERE source = \'global\'')).scalar_one()


def _values(table):
    result = {}
    for column in table.columns:
        if isinstance(column.type, Boolean):
            value = False
        elif isinstance(column.type, DateTime):
            value = datetime(2026, 10, 23, tzinfo=timezone.utc)
        elif isinstance(column.type, Integer):
            value = 1
        elif isinstance(column.type, Float):
            value = 0.5
        elif isinstance(column.type, JSON):
            value = {}
        else:
            value = "synthetic"
        result[column.name] = value
    return result


@pytest.mark.parametrize("source", WATCHED_TABLES)
def test_every_report_source_counts_insert_real_update_delete_and_transaction_rollback(database, source):
    table = Base.metadata.tables[source]
    column = next(column for column in source_columns(source) if not table.c[column].primary_key)
    with database.connect() as db:
        original = _epoch(db)
        db.execute(table.insert().values(**_values(table)))
        assert _epoch(db) == original + 1
        db.execute(text(f'UPDATE "{source}" SET "{column}" = "{column}"'))
        assert _epoch(db) == original + 1
        db.execute(text(f'UPDATE "{source}" SET "{column}" = :changed'), {"changed": "changed"})
        assert _epoch(db) == original + 2
        db.execute(text(f'DELETE FROM "{source}"'))
        assert _epoch(db) == original + 3
        db.rollback()
        assert _epoch(db) == original


def test_migration_is_idempotent_and_missing_or_modified_trigger_disables_cache(database):
    reader = SQLReportReadRepository(sessionmaker(bind=database))
    token = reader.read_token()
    assert token is not None
    apply(database)
    assert reader.read_token() == token
    name = next(iter(expected_triggers()))
    with database.begin() as db:
        db.execute(text(f'DROP TRIGGER "{name}"'))
    assert reader.read_token() is None
    apply(database)
    assert reader.read_token() is not None and reader.read_token() != token
    with database.begin() as db:
        db.execute(text(f'UPDATE "{TABLE}" SET protocol = \'unknown\''))
    assert reader.read_token() is None
    apply(database)
    assert reader.read_token() is not None


def test_lease_updates_do_not_invalidate_but_status_and_payload_do(database):
    table = Base.metadata.tables["generation_jobs"]
    with database.begin() as db:
        db.execute(table.insert().values(**_values(table)))
        initial = _epoch(db)
        db.execute(text("UPDATE generation_jobs SET claim_owner='worker', claim_epoch=9, claim_count=10, lease_expires_at='2026-10-24', next_attempt_at='2026-10-25'"))
        assert _epoch(db) == initial
        db.execute(text("UPDATE generation_jobs SET status='completed'"))
        assert _epoch(db) == initial + 1
        db.execute(text("UPDATE generation_jobs SET request_payload='{}'"))
        # Same JSON bytes are a no-op; changed focus input is observable.
        db.execute(text('UPDATE generation_jobs SET request_payload=:value'), {"value": '{"constraints":{"target_skill_node_ids":["node"]}}'})
        assert _epoch(db) == initial + 2


def test_rollback_preserves_facts_and_unrelated_triggers_and_reinstall_gets_new_identity(database):
    reader = SQLReportReadRepository(sessionmaker(bind=database))
    token = reader.read_token()
    with database.begin() as db:
        db.execute(text('CREATE TABLE unrelated (id TEXT)'))
        db.execute(text('CREATE TRIGGER untouched AFTER INSERT ON unrelated BEGIN SELECT 1; END'))
        db.execute(text("INSERT INTO unrelated VALUES ('preserved')"))
    rollback(database)
    rollback(database)
    assert TABLE not in inspect(database).get_table_names()
    assert reader.read_token() is None
    with database.connect() as db:
        assert db.execute(text("SELECT id FROM unrelated")).scalar_one() == "preserved"
        assert db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalar_one() == "untouched"
        names = {row[0] for row in db.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))}
        assert not set(INDEXES) & names
    apply(database)
    assert reader.read_token() is not None and reader.read_token()[0] != token[0]


def test_old_partial_database_can_migrate_repeatedly_but_never_claims_complete_coverage(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE learner_profiles (learner_id TEXT PRIMARY KEY, learning_goal TEXT)"))
        db.execute(text("INSERT INTO learner_profiles VALUES ('old', 'retained')"))
    apply(engine)
    apply(engine)
    assert SQLReportReadRepository(sessionmaker(bind=engine)).read_token() is None
    with engine.connect() as db:
        assert db.execute(text("SELECT learning_goal FROM learner_profiles")).scalar_one() == "retained"
    rollback(engine)
    engine.dispose()
