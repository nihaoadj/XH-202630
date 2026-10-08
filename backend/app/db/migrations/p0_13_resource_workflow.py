"""Add resource specs and text resource executions."""

from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine

from app.db.migrations.p0_09 import rebuild_sqlite_generated_resources_table
from app.db.shared.models import Base


MIGRATION_ID = "20260820_p0_13_resource_workflow"


def apply_p0_13_resource_workflow_migration(engine: Engine) -> None:
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    if "generated_resources" in tables:
        # Early SQLite installations encoded the old (run_id, resource_type,
        # version) identity as an anonymous UNIQUE table constraint. Unlike an
        # index it cannot be dropped in-place. Rebuild only when that exact
        # obsolete constraint is present; the helper copies all existing data
        # and recreates the current ORM's foreign keys and indexes.
        legacy_unique_constraint = any(
            set(item.get("column_names") or []) == {"run_id", "resource_type", "version"}
            for item in inspector.get_unique_constraints("generated_resources")
        )
        if engine.url.get_backend_name() == "sqlite" and legacy_unique_constraint:
            rebuild_sqlite_generated_resources_table(engine)
            inspector = inspect(engine)
        expected = {
            "resource_spec_id": "VARCHAR(64)",
            "resource_family_id": "VARCHAR(64)",
            "representation": "VARCHAR(16) NOT NULL DEFAULT 'text'",
        }
        columns = {item["name"] for item in inspector.get_columns("generated_resources")}
        with engine.begin() as connection:
            # A previous interrupted attempt may have created one of the
            # post-migration indexes before the data backfill committed.
            # Remove them before assigning the shared legacy spec identity.
            connection.execute(text("DROP INDEX IF EXISTS uq_generated_resources_spec_representation_version"))
            connection.execute(text("DROP INDEX IF EXISTS uq_generated_resources_legacy_run_type_version"))
            for column, ddl in expected.items():
                if column not in columns:
                    connection.execute(text(
                        f"ALTER TABLE generated_resources ADD COLUMN {column} {ddl}"
                    ))
            # Legacy runs had no spec/representation columns. Backfill one
            # stable spec identity per resource before creating the new
            # (spec, representation, version) unique index.
            connection.execute(text(
                "UPDATE generated_resources SET "
                "resource_spec_id = 'legacy-' || run_id || '-' || substr(resource_type, 1, 16) || '-' || version, "
                "resource_family_id = 'legacy-' || run_id || '-' || substr(resource_type, 1, 16) || '-' || version, "
                "representation = 'text' "
                "WHERE resource_spec_id IS NULL OR resource_spec_id LIKE 'legacy-%'"
            ))

    # These tables are additive and use the same ORM definitions as runtime.
    # The current deployment and migration evidence cover SQLite; other
    # dialect branches remain optional and require separate validation.
    Base.metadata.tables["resource_specs"].create(engine, checkfirst=True)
    Base.metadata.tables["resource_executions"].create(engine, checkfirst=True)

    execution_columns = {
        item["name"] for item in inspect(engine).get_columns("resource_executions")
    }
    if "worker_step_id" not in execution_columns:
        with engine.begin() as connection:
            connection.execute(text(
                "ALTER TABLE resource_executions ADD COLUMN worker_step_id VARCHAR(64)"
            ))

    with engine.begin() as connection:
        connection.execute(text("DROP INDEX IF EXISTS uq_generated_resources_run_type_version"))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generated_resources_spec_representation_version "
            "ON generated_resources(run_id, resource_spec_id, representation, version) "
            "WHERE resource_spec_id IS NOT NULL"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_generated_resources_legacy_run_type_version "
            "ON generated_resources(run_id, resource_type, version) "
            "WHERE resource_spec_id IS NULL"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_generated_resources_family_representation "
            "ON generated_resources(resource_family_id, representation, publication_status)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_resource_executions_worker_step_id "
            "ON resource_executions(worker_step_id)"
        ))
        if "schema_migrations" in set(inspect(engine).get_table_names()):
            exists = connection.execute(text(
                "SELECT 1 FROM schema_migrations WHERE migration_id = :migration_id"
            ), {"migration_id": MIGRATION_ID}).first()
            if exists is None:
                connection.execute(text(
                    "INSERT INTO schema_migrations (migration_id) VALUES (:migration_id)"
                ), {"migration_id": MIGRATION_ID})
