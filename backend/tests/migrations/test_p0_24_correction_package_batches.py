import json

from sqlalchemy import create_engine, text

from app.db.migrations.p0_24_correction_package_batches import (
    MIGRATION_ID,
    apply_p0_24_correction_package_batches_migration,
)


def test_correction_package_is_backfilled_into_its_source_batch(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'correction-batches.sqlite'}")
    with engine.begin() as db:
        db.exec_driver_sql("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)")
        db.exec_driver_sql("CREATE TABLE generation_jobs (run_id VARCHAR(64) PRIMARY KEY, batch_id VARCHAR(64), request_payload TEXT)")
        db.exec_driver_sql("CREATE TABLE generated_resources (resource_id VARCHAR(64) PRIMARY KEY, run_id VARCHAR(64), batch_id VARCHAR(64))")
        db.execute(text("INSERT INTO generation_jobs VALUES (:run, :batch, :payload)"), [
            {"run": "source-run", "batch": "resource-batch-01", "payload": "{}"},
            {"run": "correction-run", "batch": "correction-run", "payload": json.dumps({
                "constraints": {"correction_focus_snapshot": {"source_run_id": "source-run"}}
            })},
            {"run": "new-group-run", "batch": "new-group-run", "payload": "{}"},
        ])
        db.execute(text("INSERT INTO generated_resources VALUES (:id, :run, :batch)"), [
            {"id": "correction-resource", "run": "correction-run", "batch": "correction-run"},
            {"id": "new-resource", "run": "new-group-run", "batch": "new-group-run"},
        ])

    apply_p0_24_correction_package_batches_migration(engine)
    apply_p0_24_correction_package_batches_migration(engine)

    with engine.connect() as db:
        assert db.execute(text("SELECT batch_id FROM generation_jobs WHERE run_id='correction-run'")).scalar_one() == "resource-batch-01"
        assert db.execute(text("SELECT batch_id FROM generated_resources WHERE resource_id='correction-resource'")).scalar_one() == "resource-batch-01"
        assert db.execute(text("SELECT batch_id FROM generation_jobs WHERE run_id='new-group-run'")).scalar_one() == "new-group-run"
        assert db.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id=:id"), {"id": MIGRATION_ID}).scalar_one() == 1
