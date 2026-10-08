"""Small file-backed courseware smoke used by the CI fault evidence job."""

from __future__ import annotations

import sqlite3


def test_file_backed_sqlite_round_trip(tmp_path):
    path = tmp_path / "courseware-e2e.db"
    connection = sqlite3.connect(path)
    try:
        connection.execute("create table runs (run_id text primary key, status text not null)")
        connection.execute("insert into runs values (?, ?)", ("run-e2e", "queued"))
        connection.commit()
        connection.execute("update runs set status = ? where run_id = ?", ("released", "run-e2e"))
        connection.commit()
        assert connection.execute("select status from runs where run_id = ?", ("run-e2e",)).fetchone() == ("released",)
    finally:
        connection.close()
