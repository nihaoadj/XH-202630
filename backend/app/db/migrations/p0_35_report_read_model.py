"""Add transactional report invalidation and read indexes; facts stay intact."""
from __future__ import annotations

import argparse
from pathlib import Path
import uuid

from sqlalchemy import create_engine, inspect, text

from app.db.reports.watermarks import INDEXES, PROTOCOL, TABLE, WATCHED_TABLES, source_columns, trigger_definitions


def apply_p0_35_report_read_model_migration(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as db:
        db.execute(text(f'CREATE TABLE IF NOT EXISTS "{TABLE}" (source TEXT PRIMARY KEY, installation_id TEXT NOT NULL, protocol TEXT NOT NULL, epoch INTEGER NOT NULL DEFAULT 0)'))
        db.execute(text(f'INSERT OR IGNORE INTO "{TABLE}" (source, installation_id, protocol, epoch) VALUES (\'global\', :identity, :protocol, 0)'), {"identity": uuid.uuid4().hex, "protocol": PROTOCOL})
        tables = set(inspect(db).get_table_names())
        installed = dict(db.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'trigger' AND name LIKE 'trg_report_%'")).all())
        changed = db.execute(text(f'SELECT protocol FROM "{TABLE}" WHERE source = \'global\'')).scalar_one() != PROTOCOL
        for source in WATCHED_TABLES:
            if source not in tables:
                continue
            available = {column["name"] for column in inspect(db).get_columns(source)}
            columns = [column for column in source_columns(source) if column in available]
            if not columns:
                continue
            for name, sql in trigger_definitions(source, columns):
                if installed.get(name) == sql:
                    continue
                db.execute(text(f'DROP TRIGGER IF EXISTS "{name}"'))
                db.execute(text(sql))
                changed = True
        for name, (source, columns) in INDEXES.items():
            if source in tables:
                available = {column["name"] for column in inspect(db).get_columns(source)}
                if all(part.strip().split()[0] in available for part in columns.split(",")):
                    db.execute(text(f'CREATE INDEX IF NOT EXISTS "{name}" ON "{source}" ({columns})'))
        if changed:
            db.execute(text(f'UPDATE "{TABLE}" SET installation_id = :identity, protocol = :protocol, epoch = 0 WHERE source = \'global\''), {"identity": uuid.uuid4().hex, "protocol": PROTOCOL})


def rollback_p0_35_report_read_model_migration(engine) -> None:
    if engine.dialect.name != "sqlite":
        return
    with engine.begin() as db:
        for source in WATCHED_TABLES:
            for name, _sql in trigger_definitions(source):
                db.execute(text(f'DROP TRIGGER IF EXISTS "{name}"'))
        for name in INDEXES:
            db.execute(text(f'DROP INDEX IF EXISTS "{name}"'))
        db.execute(text(f'DROP TABLE IF EXISTS "{TABLE}"'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True, help="Existing SQLite file; stop writers and back up before maintenance")
    parser.add_argument("--rollback", action="store_true")
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("--database must name an existing SQLite file")
    engine = create_engine(f"sqlite:///{args.database.resolve().as_posix()}")
    try:
        (rollback_p0_35_report_read_model_migration if args.rollback else apply_p0_35_report_read_model_migration)(engine)
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
