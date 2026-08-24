"""P0-09 database integrity guards for resource version persistence."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.schema import CreateTable

from app.db.shared.integrity import (
    assert_integrity_migration_preconditions,
    inspect_database_integrity,
)
from app.db.shared.models import GeneratedResourceORM


MIGRATION_ID = "20260815_p0_09_database_integrity"
RESOURCE_VERSION_UNIQUE_INDEX = "uq_generated_resources_run_type_version"
SQLITE_TEMP_RESOURCE_TABLE = "_p0_09_generated_resources"


def rebuild_sqlite_generated_resources_table(engine: Engine) -> None:
    """Rebuild one clean legacy table so declared resource FKs become real SQLite FKs."""
    current_columns = [
        item["name"] for item in inspect(engine).get_columns("generated_resources")
    ]
    model_columns = {column.name for column in GeneratedResourceORM.__table__.columns}
    copy_columns = [column for column in current_columns if column in model_columns]
    quoted_columns = ", ".join(f'"{column}"' for column in copy_columns)

    create_sql = str(
        CreateTable(GeneratedResourceORM.__table__).compile(dialect=engine.dialect)
    )
    expected_prefix = "CREATE TABLE generated_resources"
    if expected_prefix not in create_sql:
        raise RuntimeError("RESOURCE_TABLE_DDL_UNEXPECTED")
    create_sql = create_sql.replace(
        expected_prefix,
        f"CREATE TABLE {SQLITE_TEMP_RESOURCE_TABLE}",
        1,
    )

    raw_connection = engine.raw_connection()
    cursor = raw_connection.cursor()
    try:
        raw_connection.rollback()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN IMMEDIATE")
        cursor.execute(f"DROP TABLE IF EXISTS {SQLITE_TEMP_RESOURCE_TABLE}")
        cursor.execute(create_sql)
        if copy_columns:
            cursor.execute(
                f"INSERT INTO {SQLITE_TEMP_RESOURCE_TABLE} ({quoted_columns}) "
                f"SELECT {quoted_columns} FROM generated_resources"
            )
        cursor.execute("DROP TABLE generated_resources")
        cursor.execute(
            f"ALTER TABLE {SQLITE_TEMP_RESOURCE_TABLE} RENAME TO generated_resources"
        )
        violations = cursor.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"FOREIGN_KEY_VIOLATIONS_AFTER_REBUILD:{len(violations)}")
        raw_connection.commit()
    except Exception:
        raw_connection.rollback()
        raise
    finally:
        cursor.execute("PRAGMA foreign_keys = ON")
        enabled = cursor.execute("PRAGMA foreign_keys").fetchone()
        cursor.close()
        raw_connection.close()
        if not enabled or int(enabled[0]) != 1:
            raise RuntimeError("SQLITE_FOREIGN_KEYS_NOT_RESTORED")

    for index in GeneratedResourceORM.__table__.indexes:
        index.create(bind=engine, checkfirst=True)
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_generated_resources_publication "
            "ON generated_resources (learner_id, publication_status, created_at)"
        ))


def apply_p0_09_migration(engine: Engine) -> None:
    """Add integrity guards without deleting or inventing legacy rows."""
    tables = set(inspect(engine).get_table_names())
    if "generated_resources" not in tables:
        return

    report = inspect_database_integrity(engine)
    assert_integrity_migration_preconditions(report)

    if (
        engine.url.get_backend_name() == "sqlite"
        and report["missing_resource_foreign_keys"]
    ):
        rebuild_sqlite_generated_resources_table(engine)
        report = inspect_database_integrity(engine)
        assert_integrity_migration_preconditions(report)
        if report["missing_resource_foreign_keys"]:
            raise RuntimeError("RESOURCE_FOREIGN_KEYS_NOT_CREATED")

    resource_columns = {
        item["name"] for item in inspect(engine).get_columns("generated_resources")
    }
    with engine.begin() as connection:
        # P0-13 replaces this legacy type-level identity with the richer
        # (resource_spec_id, representation, version) identity.  Recreating
        # the old index after that migration makes a text guide and its HTML
        # sibling collide as the same ``resource_type`` version.
        if (
            not report["resource_version_unique"]
            and "resource_spec_id" not in resource_columns
            # P0-13 will replace this legacy identity after inferring
            # text/HTML from these columns. Creating the old index here would
            # reject valid legacy text+HTML siblings before that migration runs.
            and not {"mime_type", "storage_type"}.issubset(resource_columns)
        ):
            connection.execute(text(
                f"CREATE UNIQUE INDEX IF NOT EXISTS {RESOURCE_VERSION_UNIQUE_INDEX} "
                "ON generated_resources (run_id, resource_type, version)"
            ))
        if "schema_migrations" in tables:
            row = connection.execute(
                text(
                    "SELECT migration_id FROM schema_migrations "
                    "WHERE migration_id = :migration_id"
                ),
                {"migration_id": MIGRATION_ID},
            ).first()
            if not row:
                connection.execute(
                    text("INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"),
                    {"migration_id": MIGRATION_ID},
                )
