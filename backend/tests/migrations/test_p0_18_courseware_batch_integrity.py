import json

from sqlalchemy import create_engine, text

from app.db.migrations.p0_18_courseware_batch_integrity import apply_p0_18_courseware_batch_integrity_migration


def _old_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old-courseware.sqlite'}")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE courseware_generation_jobs (run_id VARCHAR(64) PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE courseware_resources (resource_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64))")
        db.exec_driver_sql("CREATE TABLE courseware_source_links (courseware_resource_id VARCHAR(64), source_snapshot TEXT NOT NULL)")
        db.exec_driver_sql("INSERT INTO courseware_generation_jobs(run_id) VALUES ('run-1'), ('run-2'), ('run-3'), ('run-4')")
        db.exec_driver_sql("INSERT INTO courseware_resources(resource_id, run_id) VALUES ('resource-1','run-1'), ('resource-2','run-2'), ('resource-3','run-3'), ('resource-4','run-4')")
        db.execute(text("INSERT INTO courseware_source_links(courseware_resource_id, source_snapshot) VALUES (:resource, :snapshot)"), [
            {"resource": "resource-1", "snapshot": json.dumps({"batch_id": "batch-1"})},
            {"resource": "resource-1", "snapshot": json.dumps({"batch_id": "batch-1"})},
            {"resource": "resource-2", "snapshot": json.dumps({"batch_id": "batch-a"})},
            {"resource": "resource-2", "snapshot": json.dumps({"batch_id": "batch-b"})},
            {"resource": "resource-3", "snapshot": json.dumps({"topic": "missing"})},
            {"resource": "resource-4", "snapshot": "not-json"},
        ])
    return engine


def test_p0_18_is_idempotent_and_only_backfills_provable_unique_batch(tmp_path):
    engine = _old_database(tmp_path)
    apply_p0_18_courseware_batch_integrity_migration(engine)
    apply_p0_18_courseware_batch_integrity_migration(engine)
    with engine.connect() as db:
        columns = {row[1] for row in db.exec_driver_sql("PRAGMA table_info(courseware_generation_jobs)")}
        assert "source_batch_id" in columns
        assert {row[0]: row[1] for row in db.execute(text("SELECT resource_id, batch_id FROM courseware_resources")).all()} == {
            "resource-1": "batch-1", "resource-2": None, "resource-3": None, "resource-4": None,
        }
        assert db.execute(text("SELECT source_batch_id FROM courseware_generation_jobs WHERE run_id='run-1'")).scalar_one() == "batch-1"
        assert db.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id='20260823_p0_18_courseware_batch_integrity'")).scalar_one() == 1
