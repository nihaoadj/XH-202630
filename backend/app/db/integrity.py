"""Read-only database integrity inspection shared by migrations and operators."""

from __future__ import annotations

from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine


RESOURCE_VERSION_COLUMNS = ("run_id", "resource_type", "version")
EXPECTED_RESOURCE_FOREIGN_KEYS = {
    "run_id": ("agent_runs", "run_id"),
    "generation_step_id": ("agent_steps", "step_id"),
    "parent_resource_id": ("generated_resources", "resource_id"),
}


class DatabaseIntegrityError(RuntimeError):
    """The schema cannot be upgraded safely without manual data repair."""


def _has_resource_version_unique(inspector) -> bool:
    expected = list(RESOURCE_VERSION_COLUMNS)
    constraints = inspector.get_unique_constraints("generated_resources")
    indexes = inspector.get_indexes("generated_resources")
    return any(list(item.get("column_names") or []) == expected for item in constraints) or any(
        bool(item.get("unique")) and list(item.get("column_names") or []) == expected
        for item in indexes
    )


def inspect_database_integrity(engine: Engine) -> dict[str, Any]:
    """Return a sanitized, read-only integrity report for the configured database."""
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    backend = engine.url.get_backend_name()
    report: dict[str, Any] = {
        "backend": backend,
        "table_count": len(tables),
        "foreign_keys_enabled": None,
        "foreign_key_violations": [],
        "resource_version_duplicates": [],
        "resource_version_null_count": 0,
        "resource_version_unique": False,
        "missing_resource_foreign_keys": [],
        "resource_reference_orphans": {},
    }

    with engine.connect() as connection:
        if backend == "sqlite":
            report["foreign_keys_enabled"] = bool(
                int(connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one())
            )
            report["foreign_key_violations"] = [
                {
                    "table": row[0],
                    "row_id": row[1],
                    "parent_table": row[2],
                    "foreign_key_id": row[3],
                }
                for row in connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            ]

        if "generated_resources" in tables:
            columns = {item["name"] for item in inspector.get_columns("generated_resources")}
            missing_columns = set(RESOURCE_VERSION_COLUMNS) - columns
            if missing_columns:
                report["missing_resource_version_columns"] = sorted(missing_columns)
            else:
                report["resource_version_duplicates"] = [
                    {
                        "run_id": row[0],
                        "resource_type": row[1],
                        "version": row[2],
                        "count": int(row[3]),
                    }
                    for row in connection.execute(text(
                        "SELECT run_id, resource_type, version, COUNT(*) "
                        "FROM generated_resources WHERE run_id IS NOT NULL "
                        "GROUP BY run_id, resource_type, version "
                        "HAVING COUNT(*) > 1"
                    )).fetchall()
                ]
                report["resource_version_null_count"] = int(connection.execute(text(
                    "SELECT COUNT(*) FROM generated_resources "
                    "WHERE run_id IS NOT NULL AND version IS NULL"
                )).scalar_one())
                report["resource_version_unique"] = _has_resource_version_unique(inspector)

            actual_foreign_keys = {
                column: (item.get("referred_table"), (item.get("referred_columns") or [None])[0])
                for item in inspector.get_foreign_keys("generated_resources")
                for column in item.get("constrained_columns") or []
            }
            report["missing_resource_foreign_keys"] = sorted(
                column
                for column, target in EXPECTED_RESOURCE_FOREIGN_KEYS.items()
                if actual_foreign_keys.get(column) != target
            )

            reference_checks = {
                "run_id": ("agent_runs", "run_id"),
                "generation_step_id": ("agent_steps", "step_id"),
                "parent_resource_id": ("generated_resources", "resource_id"),
            }
            resource_orphans = {}
            for column, (parent_table, parent_column) in reference_checks.items():
                if column not in columns:
                    continue
                if parent_table not in tables:
                    count = int(connection.execute(text(
                        f"SELECT COUNT(*) FROM generated_resources WHERE {column} IS NOT NULL"
                    )).scalar_one())
                    examples = []
                else:
                    rows = connection.execute(text(
                        f"SELECT child.resource_id, child.{column} "
                        "FROM generated_resources AS child "
                        f"LEFT JOIN {parent_table} AS parent "
                        f"ON child.{column} = parent.{parent_column} "
                        f"WHERE child.{column} IS NOT NULL AND parent.{parent_column} IS NULL "
                        "ORDER BY child.resource_id"
                    )).fetchall()
                    count = len(rows)
                    examples = [
                        {"resource_id": row[0], "missing_reference": row[1]}
                        for row in rows[:20]
                    ]
                if count:
                    resource_orphans[column] = {
                        "count": count,
                        "examples": examples,
                    }
            report["resource_reference_orphans"] = resource_orphans

    return report


def assert_integrity_migration_preconditions(report: dict[str, Any]) -> None:
    """Fail closed when an automatic uniqueness upgrade would hide bad data."""
    missing_columns = report.get("missing_resource_version_columns", [])
    if missing_columns:
        raise DatabaseIntegrityError(
            "RESOURCE_VERSION_COLUMNS_MISSING:" + ",".join(missing_columns)
        )
    if report.get("foreign_key_violations"):
        raise DatabaseIntegrityError(
            f"FOREIGN_KEY_VIOLATIONS:{len(report['foreign_key_violations'])}"
        )
    if report.get("resource_version_duplicates"):
        raise DatabaseIntegrityError(
            f"RESOURCE_VERSION_DUPLICATES:{len(report['resource_version_duplicates'])}"
        )
    if report.get("resource_version_null_count"):
        raise DatabaseIntegrityError(
            f"RESOURCE_VERSION_NULLS:{report['resource_version_null_count']}"
        )
    if report.get("resource_reference_orphans"):
        count = sum(
            item["count"] for item in report["resource_reference_orphans"].values()
        )
        raise DatabaseIntegrityError(f"RESOURCE_REFERENCE_ORPHANS:{count}")
