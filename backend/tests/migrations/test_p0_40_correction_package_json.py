"""Old resource rows survive additive, repeatable correction-package migration."""
from sqlalchemy import create_engine, inspect, text

from app.db.migrations.p0_40_correction_package_json import apply_p0_40_correction_package_json_migration


def test_old_database_migration_is_repeatable_and_preserves_markdown(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as db:
        db.execute(text("CREATE TABLE generated_resources (resource_id TEXT PRIMARY KEY, content_text TEXT)"))
        db.execute(text("CREATE TABLE schema_migrations (migration_id TEXT PRIMARY KEY)"))
        db.execute(text("INSERT INTO generated_resources VALUES ('old', '# legacy')"))
    apply_p0_40_correction_package_json_migration(engine)
    apply_p0_40_correction_package_json_migration(engine)
    assert {"correction_package_payload", "correction_package_payload_hash"} <= {
        column["name"] for column in inspect(engine).get_columns("generated_resources")}
    with engine.connect() as db:
        row = db.execute(text("SELECT * FROM generated_resources")).mappings().one()
        assert row["content_text"] == "# legacy"
        assert row["correction_package_payload"] is None
        assert db.execute(text("SELECT count(*) FROM schema_migrations")).scalar_one() == 1
    engine.dispose()
