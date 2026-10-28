"""Add an explicit identity revision to immutable knowledge document versions."""

from __future__ import annotations

from copy import copy

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateColumn, CreateIndex, CreateTable, DefaultClause

from app.db.shared.models import KnowledgeDocumentVersionORM


MIGRATION_ID = "20261027_p0_34_knowledge_identity_revision"
REQUIRED_PREVIOUS_MIGRATION_ID = "20260829_p0_33_chunk_skill_node_mappings"
TABLE_NAME = "knowledge_document_versions"
TEMP_TABLE_NAME = "_p0_34_knowledge_document_versions"
IDENTITY_REVISION_COLUMN = "identity_revision"
LEGACY_UNIQUE_COLUMNS = (
    "knowledge_base_id",
    "document_id",
    "content_hash",
)
TARGET_UNIQUE_COLUMNS = (
    "knowledge_base_id",
    "document_id",
    "content_hash",
    IDENTITY_REVISION_COLUMN,
)


def _quote(engine: Engine, identifier: str) -> str:
    return engine.dialect.identifier_preparer.quote(identifier)


def _schema_state(engine: Engine) -> tuple[bool, bool, list[dict]]:
    """Validate the expected old/new table shape without widening migration scope."""
    tables = set(inspect(engine).get_table_names())
    required_tables = {
        "knowledge_bases",
        "knowledge_chunk_versions",
        "knowledge_chunk_skill_node_mappings",
        "schema_migrations",
        TABLE_NAME,
    }
    missing_tables = required_tables - tables
    if missing_tables:
        raise RuntimeError("P0_34_REQUIRED_TABLES_MISSING")
    if TEMP_TABLE_NAME in tables:
        raise RuntimeError("P0_34_TEMP_TABLE_ALREADY_EXISTS")

    migration_columns = {
        column["name"] for column in inspect(engine).get_columns("schema_migrations")
    }
    if "migration_id" not in migration_columns:
        raise RuntimeError("P0_34_MIGRATION_REGISTRY_INVALID")
    migrations = set()
    with engine.connect() as connection:
        migrations = {
            row[0]
            for row in connection.execute(text("SELECT migration_id FROM schema_migrations"))
        }
    if REQUIRED_PREVIOUS_MIGRATION_ID not in migrations:
        raise RuntimeError("P0_34_PREVIOUS_MIGRATION_MISSING")

    inspector = inspect(engine)
    columns = {
        column["name"] for column in inspector.get_columns(TABLE_NAME)
    }
    model_columns = {
        column.name for column in KnowledgeDocumentVersionORM.__table__.columns
    }
    required_columns = model_columns - {IDENTITY_REVISION_COLUMN}
    if not required_columns.issubset(columns):
        raise RuntimeError("P0_34_REQUIRED_COLUMNS_MISSING")
    if columns - model_columns:
        raise RuntimeError("P0_34_UNEXPECTED_COLUMNS")

    primary_key = inspector.get_pk_constraint(TABLE_NAME).get("constrained_columns") or []
    if primary_key != ["document_version"]:
        raise RuntimeError("P0_34_DOCUMENT_VERSION_PRIMARY_KEY_INVALID")

    unique_constraints = {
        tuple(item.get("column_names") or ())
        for item in inspector.get_unique_constraints(TABLE_NAME)
    }
    if unique_constraints == {TARGET_UNIQUE_COLUMNS}:
        if IDENTITY_REVISION_COLUMN not in columns:
            raise RuntimeError("P0_34_TARGET_SCHEMA_INCOMPLETE")
        target_schema = True
    elif unique_constraints == {LEGACY_UNIQUE_COLUMNS}:
        target_schema = False
    else:
        raise RuntimeError("P0_34_UNEXPECTED_UNIQUE_CONSTRAINTS")
    if target_schema and IDENTITY_REVISION_COLUMN not in columns:
        raise RuntimeError("P0_34_TARGET_SCHEMA_INCOMPLETE")

    recorded = MIGRATION_ID in migrations
    if recorded and not target_schema:
        raise RuntimeError("P0_34_MIGRATION_MARKED_BUT_SCHEMA_MISSING")

    indexes = inspector.get_indexes(TABLE_NAME)
    model_index_names = {
        index.name for index in KnowledgeDocumentVersionORM.__table__.indexes
    }
    for index in indexes:
        if index.get("name") in model_index_names:
            continue
        index_columns = index.get("column_names")
        if not index_columns or any(name not in model_columns for name in index_columns):
            raise RuntimeError("P0_34_UNSUPPORTED_EXISTING_INDEX")
        options = index.get("dialect_options") or {}
        if any(value is not None for value in options.values()):
            raise RuntimeError("P0_34_UNSUPPORTED_EXISTING_INDEX")

    return target_schema, recorded, indexes


def _check_foreign_keys(cursor) -> None:
    violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"P0_34_FOREIGN_KEY_VIOLATIONS:{len(violations)}")


def _rebuild_sqlite_table(engine: Engine, existing_indexes: list[dict]) -> None:
    model_table = KnowledgeDocumentVersionORM.__table__
    model_columns = [column.name for column in model_table.columns]
    old_column_info = inspect(engine).get_columns(TABLE_NAME)
    old_columns = {item["name"] for item in old_column_info}
    copy_columns = [name for name in model_columns if name != IDENTITY_REVISION_COLUMN]
    if not set(copy_columns).issubset(old_columns):
        raise RuntimeError("P0_34_REQUIRED_COLUMNS_MISSING")

    preparer = engine.dialect.identifier_preparer
    quoted_table = _quote(engine, TABLE_NAME)
    quoted_temp = _quote(engine, TEMP_TABLE_NAME)
    insert_columns = [*copy_columns, IDENTITY_REVISION_COLUMN]
    quoted_insert_columns = ", ".join(_quote(engine, name) for name in insert_columns)
    select_expressions = [
        _quote(engine, name) for name in copy_columns
    ]
    if IDENTITY_REVISION_COLUMN in old_columns:
        select_expressions.append(
            f"COALESCE({_quote(engine, IDENTITY_REVISION_COLUMN)}, '')"
        )
    else:
        select_expressions.append("''")

    create_sql = str(CreateTable(model_table).compile(dialect=engine.dialect))
    # The revision migration must not silently remove legacy SQL defaults.
    # Compile copied columns so the global ORM metadata is never mutated.
    for info in old_column_info:
        if info['default'] is None or info['name'] == IDENTITY_REVISION_COLUMN:
            continue
        original = model_table.c[info['name']]
        replacement = copy(original)
        replacement.server_default = DefaultClause(text(str(info['default'])))
        original_sql = str(CreateColumn(original).compile(dialect=engine.dialect))
        replacement_sql = str(CreateColumn(replacement).compile(dialect=engine.dialect))
        create_sql = create_sql.replace('\t' + original_sql, '\t' + replacement_sql, 1)
    expected_prefix = f"CREATE TABLE {TABLE_NAME}"
    if expected_prefix not in create_sql:
        raise RuntimeError("P0_34_TABLE_DDL_UNEXPECTED")
    create_sql = create_sql.replace(
        expected_prefix,
        f"CREATE TABLE {TEMP_TABLE_NAME}",
        1,
    )

    model_indexes = sorted(
        model_table.indexes,
        key=lambda index: index.name or "",
    )
    model_index_names = {index.name for index in model_indexes}
    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    foreign_keys_enabled = False
    try:
        raw_connection.rollback()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(create_sql)
        cursor.execute(
            f"INSERT INTO {quoted_temp} ({quoted_insert_columns}) "
            f"SELECT {', '.join(select_expressions)} FROM {quoted_table}"
        )
        cursor.execute(f"DROP TABLE {quoted_table}")
        cursor.execute(
            f"ALTER TABLE {quoted_temp} RENAME TO {preparer.quote(TABLE_NAME)}"
        )

        for index in model_indexes:
            cursor.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))
        for index in existing_indexes:
            name = index["name"]
            if name in model_index_names:
                continue
            unique = "UNIQUE " if index.get("unique") else ""
            index_columns = ", ".join(
                _quote(engine, column) for column in index["column_names"]
            )
            cursor.execute(
                f"CREATE {unique}INDEX {_quote(engine, name)} "
                f"ON {quoted_table} ({index_columns})"
            )

        _check_foreign_keys(cursor)
        cursor.execute(
            "INSERT OR IGNORE INTO schema_migrations (migration_id) VALUES (?)",
            (MIGRATION_ID,),
        )
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            foreign_keys_enabled = int(cursor.execute("PRAGMA foreign_keys").fetchone()[0]) == 1
        finally:
            cursor.close()
            raw_connection.close()
        if not foreign_keys_enabled:
            raise RuntimeError("P0_34_SQLITE_FOREIGN_KEYS_NOT_RESTORED")


def _record_current_schema(engine: Engine) -> None:
    """Record a schema already created from the current ORM metadata."""
    with engine.begin() as connection:
        for index in KnowledgeDocumentVersionORM.__table__.indexes:
            index.create(bind=connection, checkfirst=True)
        violations = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"P0_34_FOREIGN_KEY_VIOLATIONS:{len(violations)}")
        connection.execute(
            text("INSERT OR IGNORE INTO schema_migrations (migration_id) VALUES (:id)"),
            {"id": MIGRATION_ID},
        )


def apply_p0_34_knowledge_identity_revision_migration(engine: Engine) -> None:
    """Add the revision discriminator while preserving every historical version row."""
    if engine.url.get_backend_name() != "sqlite":
        raise RuntimeError("P0_34_SQLITE_ONLY")

    target_schema, recorded, indexes = _schema_state(engine)
    if target_schema:
        _record_current_schema(engine)
        return
    if recorded:
        raise RuntimeError("P0_34_MIGRATION_MARKED_BUT_SCHEMA_MISSING")
    _rebuild_sqlite_table(engine, indexes)

    target_schema, recorded, _ = _schema_state(engine)
    if not target_schema or not recorded:
        raise RuntimeError("P0_34_MIGRATION_VERIFICATION_FAILED")


__all__ = [
    "MIGRATION_ID",
    "apply_p0_34_knowledge_identity_revision_migration",
]
