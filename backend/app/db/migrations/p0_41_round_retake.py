"""Allow multiple frozen evaluation sessions per stage without changing old IDs."""

from sqlalchemy import inspect
from sqlalchemy.schema import CreateTable

from app.db.feedback.round_models import LearningRoundEvaluationSessionORM
from app.db.migrations.p0_35_report_read_model import apply_p0_35_report_read_model_migration


def apply_p0_41_round_retake_migration(engine):
    table = LearningRoundEvaluationSessionORM.__table__
    inspector = inspect(engine)
    if not inspector.has_table(table.name):
        return
    old_columns = [column["name"] for column in inspector.get_columns(table.name)]
    if "ordinal" in old_columns:
        return
    if engine.dialect.name == "sqlite":
        _upgrade_sqlite(engine, table, old_columns)
        apply_p0_35_report_read_model_migration(engine)
        return
    with engine.begin() as db:
        db.exec_driver_sql(f"LOCK TABLE {table.name} IN ACCESS EXCLUSIVE MODE")
        if "ordinal" in {column["name"] for column in inspect(db).get_columns(table.name)}:
            return
        quote = db.dialect.identifier_preparer.quote
        for constraint in inspect(db).get_unique_constraints(table.name):
            if constraint["column_names"] == ["stage_id"]:
                db.exec_driver_sql(f"ALTER TABLE {table.name} DROP CONSTRAINT {quote(constraint['name'])}")
        db.exec_driver_sql(f"ALTER TABLE {table.name} ADD COLUMN ordinal INTEGER NOT NULL DEFAULT 1")
        db.exec_driver_sql(
            f"ALTER TABLE {table.name} ADD CONSTRAINT uq_round_session_ordinal UNIQUE (stage_id, ordinal)"
        )


def _upgrade_sqlite(engine, table, old_columns):
    temporary = f"{table.name}_p0_41"
    ddl = str(CreateTable(table).compile(dialect=engine.dialect))
    ddl = ddl.replace(f"CREATE TABLE {table.name}", f"CREATE TABLE {temporary}", 1)
    quote = engine.dialect.identifier_preparer.quote
    columns = ", ".join(quote(column) for column in old_columns)
    connection = engine.raw_connection()
    cursor = connection.cursor()
    try:
        connection.rollback()
        cursor.execute("PRAGMA foreign_keys = OFF")
        cursor.execute("BEGIN IMMEDIATE")
        # Another process may have completed the migration while we waited.
        if "ordinal" not in {row[1] for row in cursor.execute(f"PRAGMA table_info({table.name})")}:
            cursor.execute(ddl)
            cursor.execute(f"INSERT INTO {temporary} ({columns}) SELECT {columns} FROM {table.name}")
            cursor.execute(f"DROP TABLE {table.name}")
            cursor.execute(f"ALTER TABLE {temporary} RENAME TO {table.name}")
            if cursor.execute("PRAGMA foreign_key_check").fetchone():
                raise RuntimeError("Round retake migration failed foreign key validation")
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    finally:
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
        finally:
            cursor.close()
            connection.close()
