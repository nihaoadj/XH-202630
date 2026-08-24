import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db.shared.integrity import DatabaseIntegrityError, inspect_database_integrity
from app.db.migrations.p0_09 import MIGRATION_ID, apply_p0_09_migration


def _legacy_engine(tmp_path, name="p0_09.db"):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    with engine.begin() as connection:
        connection.execute(text(
            "CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"
        ))
        connection.execute(text("CREATE TABLE agent_runs (run_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text(
            "CREATE TABLE agent_steps (step_id VARCHAR(128) PRIMARY KEY, run_id VARCHAR(128))"
        ))
        connection.execute(text(
            "CREATE TABLE generated_resources ("
            "resource_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(128), "
            "generation_step_id VARCHAR(128), learner_id VARCHAR(64) NOT NULL, "
            "topic VARCHAR(256) NOT NULL, resource_type VARCHAR(32) NOT NULL, "
            "difficulty VARCHAR(16) NOT NULL, storage_type VARCHAR(16) NOT NULL DEFAULT 'text', "
            "publication_status VARCHAR(32) NOT NULL DEFAULT 'unpublished', "
            "version INTEGER, parent_resource_id VARCHAR(64), created_at DATETIME)"
        ))
    return engine


def test_p0_09_adds_resource_version_unique_guard_and_is_idempotent(tmp_path):
    engine = _legacy_engine(tmp_path)

    apply_p0_09_migration(engine)
    apply_p0_09_migration(engine)

    report = inspect_database_integrity(engine)
    assert report["resource_version_unique"] is True
    assert report["missing_resource_foreign_keys"] == []
    with engine.begin() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:migration_id"),
            {"migration_id": MIGRATION_ID},
        ).scalar_one() == 1
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, learner_id, topic, resource_type, difficulty, storage_type, "
            "publication_status, version) "
            "VALUES ('legacy-a', 'learner', 'RAG', '讲义', '初级', 'text', 'unpublished', 1)"
        ))
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, learner_id, topic, resource_type, difficulty, storage_type, "
            "publication_status, version) "
            "VALUES ('legacy-b', 'learner', 'RAG', '讲义', '初级', 'text', 'unpublished', 1)"
        ))
        connection.execute(text("INSERT INTO agent_runs VALUES ('run-a')"))
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, run_id, learner_id, topic, resource_type, difficulty, "
            "storage_type, publication_status, version) "
            "VALUES ('run-a-v1', 'run-a', 'learner', 'RAG', '讲义', "
            "'初级', 'text', 'unpublished', 1)"
        ))

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO generated_resources "
                "(resource_id, run_id, learner_id, topic, resource_type, difficulty, "
                "storage_type, publication_status, version) "
                "VALUES ('run-a-v1-duplicate', 'run-a', 'learner', 'RAG', '讲义', "
                "'初级', 'text', 'unpublished', 1)"
            ))

    resource_inspector = inspect(engine)
    unique_guards = [
        item
        for item in resource_inspector.get_indexes("generated_resources")
        if item.get("unique")
    ] + resource_inspector.get_unique_constraints("generated_resources")
    assert any(
        item["column_names"] == ["run_id", "resource_type", "version"]
        for item in unique_guards
    )


def test_p0_09_refuses_preexisting_resource_version_duplicates(tmp_path):
    engine = _legacy_engine(tmp_path, "duplicates.db")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO agent_runs VALUES ('run-a')"))
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, run_id, learner_id, topic, resource_type, difficulty, version) VALUES "
            "('a', 'run-a', 'learner', 'RAG', '讲义', '初级', 1), "
            "('b', 'run-a', 'learner', 'RAG', '讲义', '初级', 1)"
        ))

    with pytest.raises(DatabaseIntegrityError, match="RESOURCE_VERSION_DUPLICATES:1"):
        apply_p0_09_migration(engine)


def test_p0_09_allows_current_text_and_html_representations_to_share_legacy_version(tmp_path):
    engine = _legacy_engine(tmp_path, "current-representations.db")
    with engine.begin() as connection:
        connection.execute(text(
            "ALTER TABLE generated_resources ADD COLUMN resource_spec_id VARCHAR(64)"
        ))
        connection.execute(text(
            "ALTER TABLE generated_resources ADD COLUMN representation VARCHAR(16)"
        ))
        connection.execute(text("INSERT INTO agent_runs VALUES ('run-a')"))
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, run_id, resource_spec_id, representation, learner_id, topic, "
            "resource_type, difficulty, version) VALUES "
            "('guide-text', 'run-a', 'guide-spec', 'text', 'learner', 'RAG', '讲义', '初级', 1), "
            "('guide-html', 'run-a', 'guide-spec', 'html', 'learner', 'RAG', '讲义', '初级', 1)"
        ))

    apply_p0_09_migration(engine)

    with engine.connect() as connection:
        assert connection.execute(text(
            "SELECT COUNT(*) FROM generated_resources "
            "WHERE run_id='run-a' AND resource_type='讲义' AND version=1"
        )).scalar_one() == 2


def test_p0_09_refuses_null_version_for_nonlegacy_run(tmp_path):
    engine = _legacy_engine(tmp_path, "null-version.db")
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO agent_runs VALUES ('run-a')"))
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, run_id, learner_id, topic, resource_type, difficulty, version) "
            "VALUES ('a', 'run-a', 'learner', 'RAG', '讲义', '初级', NULL)"
        ))

    with pytest.raises(DatabaseIntegrityError, match="RESOURCE_VERSION_NULLS:1"):
        apply_p0_09_migration(engine)


def test_p0_09_refuses_orphan_resource_references(tmp_path):
    engine = _legacy_engine(tmp_path, "orphan.db")
    with engine.begin() as connection:
        connection.execute(text(
            "INSERT INTO generated_resources "
            "(resource_id, run_id, learner_id, topic, resource_type, difficulty, version) "
            "VALUES ('orphan', 'missing-run', 'learner', 'RAG', '讲义', '初级', 1)"
        ))

    with pytest.raises(DatabaseIntegrityError, match="RESOURCE_REFERENCE_ORPHANS:1"):
        apply_p0_09_migration(engine)
