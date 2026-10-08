from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_15_courseware_execution import MIGRATION_ID, apply_p0_15_courseware_execution_migration


def test_p0_15_is_additive_and_idempotent_for_legacy_courseware_schema(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-courseware.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE learner_profiles (learner_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE courseware_generation_jobs (run_id VARCHAR(64) PRIMARY KEY, learner_id VARCHAR(64), request_hash VARCHAR(64))"))
        connection.execute(text("CREATE TABLE courseware_resources (resource_id VARCHAR(64) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE courseware_outbox (outbox_id VARCHAR(96) PRIMARY KEY, run_id VARCHAR(64), idempotency_key VARCHAR(160))"))
        connection.execute(text("CREATE TABLE courseware_artifacts (artifact_id VARCHAR(96) PRIMARY KEY, courseware_resource_id VARCHAR(64))"))
        connection.execute(text("CREATE TABLE courseware_scene_revisions (revision_id VARCHAR(96) PRIMARY KEY, scene_id VARCHAR(96), revision_no INTEGER)"))
        connection.execute(text("CREATE TABLE courseware_events (event_id VARCHAR(96) PRIMARY KEY, run_id VARCHAR(64), event_sequence INTEGER)"))
        connection.execute(text("INSERT INTO courseware_generation_jobs (run_id, learner_id, request_hash) VALUES ('run-1', 'learner-1', 'hash')"))

    apply_p0_15_courseware_execution_migration(engine)
    apply_p0_15_courseware_execution_migration(engine)

    inspector = inspect(engine)
    job_columns = {column["name"] for column in inspector.get_columns("courseware_generation_jobs")}
    assert {"release_policy", "next_event_sequence", "deadline_at", "cancel_requested_at", "released_release_id"} <= job_columns
    assert {"courseware_workflow_checkpoints", "courseware_releases"} <= set(inspector.get_table_names())
    assert {"task_kind", "status", "claimed_by", "dead_lettered_at"} <= {
        column["name"] for column in inspector.get_columns("courseware_outbox")
    }
    assert {"release_id", "required", "artifact_status"} <= {
        column["name"] for column in inspector.get_columns("courseware_artifacts")
    }
    with engine.connect() as connection:
        assert connection.execute(text("SELECT run_id FROM courseware_generation_jobs")).scalar_one() == "run-1"
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations WHERE migration_id = :migration_id"), {
            "migration_id": MIGRATION_ID,
        }).scalar_one() == 1


def test_p0_15_backfills_event_counter_without_rewriting_history(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'history-courseware.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE courseware_generation_jobs (run_id VARCHAR(64) PRIMARY KEY, learner_id VARCHAR(64), request_hash VARCHAR(64))"))
        connection.execute(text("CREATE TABLE courseware_events (event_id VARCHAR(96) PRIMARY KEY, run_id VARCHAR(64), event_sequence INTEGER, payload JSON)"))
        connection.execute(text("CREATE TABLE courseware_scene_revisions (revision_id VARCHAR(96) PRIMARY KEY, scene_id VARCHAR(96), revision_no INTEGER)"))
        connection.execute(text("INSERT INTO courseware_generation_jobs VALUES ('run-1', 'learner-1', 'hash')"))
        connection.execute(text("INSERT INTO courseware_events VALUES ('e1', 'run-1', 1, '{}'), ('e3', 'run-1', 3, '{}')"))
    apply_p0_15_courseware_execution_migration(engine)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT next_event_sequence FROM courseware_generation_jobs WHERE run_id='run-1'")).scalar_one() == 4
        assert connection.execute(text("SELECT GROUP_CONCAT(event_id, ',') FROM courseware_events")).scalar_one() == "e1,e3"


def test_p0_15_rejects_duplicate_historical_event_sequence_without_marker(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'corrupt-courseware.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE schema_migrations (migration_id VARCHAR(128) PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE courseware_generation_jobs (run_id VARCHAR(64) PRIMARY KEY, learner_id VARCHAR(64), request_hash VARCHAR(64))"))
        connection.execute(text("CREATE TABLE courseware_events (event_id VARCHAR(96) PRIMARY KEY, run_id VARCHAR(64), event_sequence INTEGER)"))
        connection.execute(text("INSERT INTO courseware_generation_jobs VALUES ('run-1', 'learner-1', 'hash')"))
        connection.execute(text("INSERT INTO courseware_events VALUES ('e1', 'run-1', 1), ('e2', 'run-1', 1)"))
    try:
        apply_p0_15_courseware_execution_migration(engine)
    except RuntimeError as exc:
        assert str(exc) == "P0_15_DUPLICATE_EVENT_SEQUENCE"
    else:
        raise AssertionError("duplicate historical event sequence must stop migration")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM schema_migrations")).scalar_one() == 0
