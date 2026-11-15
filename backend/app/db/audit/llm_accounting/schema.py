"""SQLAlchemy table definitions owned exclusively by the accounting store."""

from __future__ import annotations

from sqlalchemy import Column, Integer, MetaData, String, Table, Text

LLM_ACCOUNTING_SCHEMA_VERSION = 1

llm_accounting_metadata = MetaData()

llm_call_observations = Table(
    "llm_call_observations",
    llm_accounting_metadata,
    Column("domain", String(32), primary_key=True),
    Column("run_id", String(256), primary_key=True),
    Column("segment_id", String(256), primary_key=True),
    Column("observation_id", Integer, primary_key=True),
    Column("stage", String(128)),
    Column("step_id", String(256)),
    Column("source_call_id", String(256)),
    Column("payload_json", Text, nullable=False),
    Column("payload_hash", String(64), nullable=False),
    Column("recorded_at", String(64), nullable=False),
)

llm_accounting_segments = Table(
    "llm_accounting_segments",
    llm_accounting_metadata,
    Column("domain", String(32), primary_key=True),
    Column("run_id", String(256), primary_key=True),
    Column("segment_id", String(256), primary_key=True),
    Column("manifest_json", Text, nullable=False),
    Column("manifest_hash", String(64), nullable=False),
    Column("expected_calls", Integer, nullable=False, default=0),
    Column("received_calls", Integer, nullable=False, default=0),
    Column("received_status", String(32), nullable=False, default="received"),
    Column("recorded_at", String(64), nullable=False),
)

llm_accounting_schema_migrations = Table(
    "llm_accounting_schema_migrations",
    llm_accounting_metadata,
    Column("version", Integer, primary_key=True),
    Column("applied_at", String(64), nullable=False),
)
