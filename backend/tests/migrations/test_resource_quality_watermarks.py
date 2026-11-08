"""T48 report-read protocol upgrade: report-read/2 watermark closure.

The quality projection reads run snapshots, steps, checkpoints, frozen specs and
the private review ledger.  Those sources were not part of the report-read/1
trigger closure, so a review correction could leave a cached report body stale.
These tests cover the protocol bump itself; the pre-existing suite continues to
cover the original sources.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import Boolean, DateTime, Float, Integer, JSON, create_engine, inspect, text
from sqlalchemy.orm import sessionmaker

from app.db.migrations.p0_35_report_read_model import (
    apply_p0_35_report_read_model_migration as apply,
    rollback_p0_35_report_read_model_migration as rollback,
)
from app.db.reports.repository import SQLReportReadRepository
from app.db.reports.watermarks import (
    PROTOCOL,
    TABLE,
    WATCHED_TABLES,
    expected_triggers,
    source_columns,
)
from app.db.shared.models import Base

QUALITY_SOURCES = (
    "agent_runs", "agent_steps", "workflow_checkpoints", "resource_specs",
    "resource_claims", "claim_judgements", "claim_evidence",
)


@pytest.fixture
def database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'quality-watermarks.db'}")
    Base.metadata.create_all(engine)
    apply(engine)
    yield engine
    engine.dispose()


def _epoch(connection):
    return connection.execute(
        text(f'SELECT epoch FROM "{TABLE}" WHERE source = \'global\''),
    ).scalar_one()


def _values(table):
    result = {}
    for column in table.columns:
        if isinstance(column.type, Boolean):
            value = False
        elif isinstance(column.type, DateTime):
            value = datetime(2026, 11, 7, tzinfo=timezone.utc)
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


def test_protocol_is_two_and_installs_every_quality_trigger_idempotently(database):
    assert PROTOCOL == "report-read/3"
    for source in QUALITY_SOURCES:
        assert source in WATCHED_TABLES
    expected = expected_triggers()
    with database.connect() as db:
        installed = {
            row[0] for row in db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
        assert set(expected) <= installed
        assert _epoch(db) >= 0
        protocol = db.execute(
            text(f'SELECT protocol FROM "{TABLE}" WHERE source = \'global\''),
        ).scalar_one()
        assert protocol == PROTOCOL
    reader = SQLReportReadRepository(sessionmaker(bind=database))
    token = reader.read_token()
    apply(database)
    assert reader.read_token() == token


@pytest.mark.parametrize("source", QUALITY_SOURCES)
def test_quality_sources_invalidate_on_insert_and_delete(database, source):
    table = Base.metadata.tables[source]
    with database.connect() as db:
        original = _epoch(db)
        db.execute(table.insert().values(**_values(table)))
        assert _epoch(db) == original + 1
        db.execute(text(f'DELETE FROM "{source}"'))
        assert _epoch(db) == original + 2
        db.rollback()
        assert _epoch(db) == original


def test_agent_run_status_correction_invalidates_but_heartbeat_does_not(database):
    table = Base.metadata.tables["agent_runs"]
    with database.begin() as db:
        db.execute(table.insert().values(**_values(table)))
        initial = _epoch(db)
        # A lease heartbeat rewrites liveness columns only; it is not report
        # content and must not evict a cached body.
        db.execute(text(
            "UPDATE agent_runs SET heartbeat_at='2026-11-08', "
            "lease_expires_at='2026-11-09', owner_instance_id='worker-2', "
            "updated_at='2026-11-08'",
        ))
        assert _epoch(db) == initial
        db.execute(text("UPDATE agent_runs SET status='completed'"))
        assert _epoch(db) == initial + 1
        db.execute(text("UPDATE agent_runs SET current_step_sequence=7"))
        assert _epoch(db) == initial + 2


@pytest.mark.parametrize("source", ("agent_steps", "workflow_checkpoints", "resource_specs"))
def test_value_correction_on_quality_source_invalidates(database, source):
    table = Base.metadata.tables[source]
    column = next(
        name for name in source_columns(source)
        if name in {"status", "state_projection", "display_order", "output_payload"}
    )
    with database.begin() as db:
        db.execute(table.insert().values(**_values(table)))
        initial = _epoch(db)
        db.execute(text(f'UPDATE "{source}" SET "{column}" = "{column}"'))
        assert _epoch(db) == initial
        db.execute(
            text(f'UPDATE "{source}" SET "{column}" = :changed'),
            {"changed": 9 if column == "display_order" else "changed"},
        )
        assert _epoch(db) == initial + 1


def test_missing_quality_trigger_disables_the_cache_and_reinstall_restores_it(database):
    reader = SQLReportReadRepository(sessionmaker(bind=database))
    token = reader.read_token()
    assert token is not None
    name = "trg_report_workflow_checkpoints_insert"
    with database.begin() as db:
        db.execute(text(f'DROP TRIGGER "{name}"'))
    assert reader.read_token() is None
    apply(database)
    restored = reader.read_token()
    assert restored is not None and restored != token


def test_protocol_downgrade_is_detected_as_unmigrated(database):
    reader = SQLReportReadRepository(sessionmaker(bind=database))
    assert reader.read_token() is not None
    with database.begin() as db:
        db.execute(text(f'UPDATE "{TABLE}" SET protocol = \'report-read/1\''))
    assert reader.read_token() is None
    apply(database)
    assert reader.read_token() is not None


def test_rollback_keeps_business_facts_and_unrelated_triggers(database):
    with database.begin() as db:
        db.execute(Base.metadata.tables["agent_runs"].insert().values(
            **_values(Base.metadata.tables["agent_runs"]),
        ))
        db.execute(text('CREATE TABLE untouched (id TEXT)'))
        db.execute(text(
            'CREATE TRIGGER untouched_trigger AFTER INSERT ON untouched '
            'BEGIN SELECT 1; END',
        ))
        db.execute(text("INSERT INTO untouched VALUES ('preserved')"))

    rollback(database)
    rollback(database)

    assert TABLE not in inspect(database).get_table_names()
    with database.connect() as db:
        assert db.execute(text("SELECT run_id FROM agent_runs")).scalar_one() == "synthetic"
        assert db.execute(text("SELECT id FROM untouched")).scalar_one() == "preserved"
        triggers = {
            row[0] for row in db.execute(text("SELECT name FROM sqlite_master WHERE type='trigger'"))
        }
        assert triggers == {"untouched_trigger"}
    assert SQLReportReadRepository(sessionmaker(bind=database)).read_token() is None

    apply(database)
    assert SQLReportReadRepository(sessionmaker(bind=database)).read_token() is not None
