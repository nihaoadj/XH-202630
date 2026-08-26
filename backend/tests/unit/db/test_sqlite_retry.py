from sqlalchemy.exc import OperationalError

from app.db.shared.retry import is_sqlite_lock_error, run_with_sqlite_retry


def test_sqlite_lock_retry_replays_idempotent_operation(monkeypatch):
    calls = []
    sleeps = []

    def operation():
        calls.append(len(calls) + 1)
        if len(calls) == 1:
            raise OperationalError("INSERT", {}, RuntimeError("database is locked"))
        return "saved"

    monkeypatch.setattr("app.db.shared.retry.time.sleep", sleeps.append)

    assert run_with_sqlite_retry(operation, attempts=3, base_delay_seconds=0.25) == "saved"
    assert calls == [1, 2]
    assert sleeps == [0.25]


def test_sqlite_retry_does_not_classify_domain_errors_as_transient():
    assert not is_sqlite_lock_error(ValueError("database is locked"))
