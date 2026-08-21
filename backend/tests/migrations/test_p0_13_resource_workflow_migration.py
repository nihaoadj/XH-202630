from __future__ import annotations

from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_13_resource_workflow import (
    apply_p0_13_resource_workflow_migration,
)


def test_p0_13_migration_is_idempotent_and_allows_text_html_pair(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resource-workflow.db'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE generated_resources (
                resource_id VARCHAR(64) PRIMARY KEY,
                run_id VARCHAR(128),
                resource_type VARCHAR(32) NOT NULL,
                version INTEGER NOT NULL,
                publication_status VARCHAR(32) NOT NULL DEFAULT 'unpublished'
            )
        """))
        connection.execute(text(
            "CREATE UNIQUE INDEX uq_generated_resources_run_type_version "
            "ON generated_resources(run_id, resource_type, version)"
        ))

    apply_p0_13_resource_workflow_migration(engine)
    apply_p0_13_resource_workflow_migration(engine)

    inspector = inspect(engine)
    assert {"resource_specs", "resource_executions"} <= set(inspector.get_table_names())
    execution_columns = {
        item["name"] for item in inspector.get_columns("resource_executions")
    }
    assert "worker_step_id" in execution_columns
    columns = {item["name"] for item in inspector.get_columns("generated_resources")}
    assert {
        "resource_spec_id",
        "resource_family_id",
        "representation",
        "derived_from_resource_id",
        "source_resource_version",
        "canonical_text_hash",
        "guide_manifest",
    } <= columns
    indexes = {item["name"] for item in inspector.get_indexes("generated_resources")}
    assert "uq_generated_resources_spec_representation_version" in indexes
    assert "uq_generated_resources_legacy_run_type_version" in indexes

    values = {
        "run_id": "run-migration",
        "resource_type": "实操指南",
        "version": 1,
        "resource_spec_id": "11111111-1111-4111-8111-111111111111",
        "resource_family_id": "22222222-2222-4222-8222-222222222222",
    }
    with engine.begin() as connection:
        for resource_id, representation in (("text-v1", "text"), ("html-v1", "html")):
            connection.execute(text("""
                    INSERT INTO generated_resources (
                        resource_id, run_id, resource_type, version,
                        resource_spec_id, resource_family_id, representation
                    ) VALUES (
                        :resource_id, :run_id, :resource_type, :version,
                        :resource_spec_id, :resource_family_id, :representation
                )
            """), {**values, "resource_id": resource_id, "representation": representation})
        count = connection.execute(text(
            "SELECT COUNT(*) FROM generated_resources WHERE resource_spec_id = :resource_spec_id"
        ), values).scalar_one()
    assert count == 2


def test_p0_13_rebuilds_legacy_sqlite_unique_constraint_for_text_html_pair(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-constraint.db'}")
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE generated_resources (
                resource_id VARCHAR(64) PRIMARY KEY,
                run_id VARCHAR(128),
                resource_type VARCHAR(32) NOT NULL,
                version INTEGER NOT NULL,
                publication_status VARCHAR(32) NOT NULL DEFAULT 'unpublished',
                UNIQUE(run_id, resource_type, version)
            )
        """))

    apply_p0_13_resource_workflow_migration(engine)
    unique_constraints = inspect(engine).get_unique_constraints("generated_resources")
    assert not any(
        set(item.get("column_names") or []) == {"run_id", "resource_type", "version"}
        for item in unique_constraints
    )

    values = {
        "run_id": "run-legacy-constraint",
        "resource_type": "实操指南",
        "version": 1,
        "learner_id": "learner-legacy-constraint",
        "topic": "迁移验证",
        "difficulty": "中级",
        "storage_type": "text",
        "publication_status": "unpublished",
        "resource_spec_id": "11111111-1111-4111-8111-111111111111",
        "resource_family_id": "22222222-2222-4222-8222-222222222222",
    }
    with engine.begin() as connection:
        for resource_id, representation in (("text-v1", "text"), ("html-v1", "html")):
            connection.execute(text("""
                INSERT INTO generated_resources (
                    resource_id, run_id, resource_type, version,
                    resource_spec_id, resource_family_id, representation,
                    learner_id, topic, difficulty, storage_type, publication_status
                ) VALUES (
                    :resource_id, :run_id, :resource_type, :version,
                    :resource_spec_id, :resource_family_id, :representation,
                    :learner_id, :topic, :difficulty, :storage_type, :publication_status
                )
            """), {**values, "resource_id": resource_id, "representation": representation})
