"""Create and verify a SQLite backup for the single-Worker courseware topology."""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--writes-stopped", action="store_true", help="required operational acknowledgement")
    args = parser.parse_args()
    if not args.writes_stopped:
        raise SystemExit("refusing backup: stop Web/Worker writes or use a separately approved snapshot workflow")
    if not args.source.is_file():
        raise SystemExit("source database does not exist")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(args.source) as source, sqlite3.connect(args.output) as target:
        source.backup(target)
    with sqlite3.connect(args.output) as restored:
        integrity = restored.execute("PRAGMA integrity_check").fetchone()[0]
        tables = sorted(row[0] for row in restored.execute("SELECT name FROM sqlite_master WHERE type='table'"))
    report = {"schema_version": "1.0", "status": "LOCAL_READY" if integrity == "ok" else "PARTIAL",
              "integrity_check": integrity, "table_count": len(tables), "backup_sha256": _sha256(args.output)}
    print(json.dumps(report, ensure_ascii=False))
    return 0 if integrity == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
