"""Migration semantics for the independent accounting database."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from sqlalchemy import create_engine, inspect

from app.db.audit.llm_accounting.migrations import (
    LLM_ACCOUNTING_SCHEMA_VERSION,
    current_schema_version,
    ensure_schema,
)
from app.db.audit.llm_accounting.schema import llm_accounting_metadata


def _engine(path: Path):
    return create_engine(f"sqlite:///{path}")


def test_new_database_is_created_with_version_one():
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / "accounting.db"
        engine = _engine(db_path)
        assert current_schema_version(engine) == 0
        version = ensure_schema(engine)
        assert version == LLM_ACCOUNTING_SCHEMA_VERSION
        assert current_schema_version(engine) == LLM_ACCOUNTING_SCHEMA_VERSION
        inspector = inspect(engine)
        assert {"llm_call_observations", "llm_accounting_segments"} <= set(
            inspector.get_table_names()
        )
        engine.dispose()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_repeated_migration_is_idempotent():
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / "accounting.db"
        engine = _engine(db_path)
        ensure_schema(engine)
        ensure_schema(engine)
        assert current_schema_version(engine) == LLM_ACCOUNTING_SCHEMA_VERSION
        engine.dispose()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_unknown_newer_version_is_rejected():
    tmp = tempfile.mkdtemp()
    try:
        db_path = Path(tmp) / "accounting.db"
        engine = _engine(db_path)
        ensure_schema(engine)
        with engine.begin() as connection:
            from datetime import datetime, timezone

            connection.execute(
                llm_accounting_metadata.tables["llm_accounting_schema_migrations"]
                .insert()
                .values(
                    version=LLM_ACCOUNTING_SCHEMA_VERSION + 1,
                    applied_at=datetime.now(timezone.utc).isoformat(),
                )
            )
        try:
            ensure_schema(engine)
            raised = False
        except RuntimeError:
            raised = True
        assert raised, "a newer unknown schema version must refuse to be read"
        engine.dispose()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_accounting_metadata_is_not_registered_with_business_base():
    from app.db.shared.models import Base

    table_names = set(Base.metadata.tables)
    assert "llm_call_observations" not in table_names
    assert "llm_accounting_segments" not in table_names
    assert llm_accounting_metadata is not Base.metadata


def test_failed_accounting_schema_leaves_business_startup_ready():
    # A failing accounting migration is isolated: nothing in the business
    # p0 migration chain references the accounting store.
    import app.db.migrations as migrations_pkg
    from pathlib import Path as _Path

    package_dir = _Path(migrations_pkg.__file__).parent
    references = [
        text
        for file in package_dir.glob("*.py")
        for text in (file.read_text(encoding="utf-8"),)
        if "llm_accounting" in text or "llm_call_observations" in text
    ]
    assert not references
