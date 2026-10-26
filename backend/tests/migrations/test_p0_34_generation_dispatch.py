from sqlalchemy import create_engine, inspect, text
from app.db.migrations.p0_34_generation_dispatch import apply_p0_34_generation_dispatch_migration


def test_existing_rows_remain_legacy_and_migration_is_repeatable(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE generation_jobs(run_id VARCHAR PRIMARY KEY, status VARCHAR, created_at DATETIME)"))
        connection.execute(text("INSERT INTO generation_jobs VALUES('old', 'queued', CURRENT_TIMESTAMP)"))
    apply_p0_34_generation_dispatch_migration(engine)
    apply_p0_34_generation_dispatch_migration(engine)
    with engine.connect() as connection:
        row = connection.execute(text("SELECT * FROM generation_jobs")).mappings().one()
        assert row['run_id'] == 'old' and row['status'] == 'queued'
        assert row['dispatch_mode'] == 'legacy' and row['claim_epoch'] == row['claim_count'] == 0
        assert row['dispatch_snapshot'] is None
    indexes = {index['name'] for index in inspect(engine).get_indexes('generation_jobs')}
    assert {'uq_generation_retry_of', 'ix_generation_dispatch_claim'} <= indexes
    engine.dispose()
