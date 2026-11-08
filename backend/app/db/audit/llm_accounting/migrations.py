"""Versioned migrations for the independent accounting database.

Business p0 migrations are untouched; this store owns its own migration
table.  A failed table creation only makes accounting unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import inspect, select
from sqlalchemy.engine import Engine

from app.db.audit.llm_accounting.schema import (
    LLM_ACCOUNTING_SCHEMA_VERSION,
    llm_accounting_metadata,
    llm_accounting_schema_migrations,
)

logger = logging.getLogger(__name__)

SUPPORTED_VERSIONS = {0, LLM_ACCOUNTING_SCHEMA_VERSION}


def current_schema_version(engine: Engine) -> int:
    """Return the applied schema version; 0 when the database is new."""

    inspector = inspect(engine)
    if not inspector.has_table(llm_accounting_schema_migrations.name):
        return 0
    with engine.connect() as connection:
        row = connection.execute(
            select(llm_accounting_schema_migrations.c.version).order_by(
                llm_accounting_schema_migrations.c.version.desc()
            )
        ).first()
    return int(row[0]) if row is not None else 0


def ensure_schema(engine: Engine) -> int:
    """Create or verify the accounting schema; returns the applied version."""

    version = current_schema_version(engine)
    if version > LLM_ACCOUNTING_SCHEMA_VERSION:
        raise RuntimeError(
            f"llm-accounting schema version {version} is newer than supported "
            f"{LLM_ACCOUNTING_SCHEMA_VERSION}"
        )
    llm_accounting_metadata.create_all(engine)
    if version < LLM_ACCOUNTING_SCHEMA_VERSION:
        with engine.begin() as connection:
            connection.execute(
                llm_accounting_schema_migrations.insert().values(
                    version=LLM_ACCOUNTING_SCHEMA_VERSION,
                    applied_at=datetime.now(timezone.utc).isoformat(),
                )
            )
    return LLM_ACCOUNTING_SCHEMA_VERSION
