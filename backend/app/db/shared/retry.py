"""Bounded retries for transient SQLite write contention."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar

from sqlalchemy.exc import OperationalError


T = TypeVar("T")


def is_sqlite_lock_error(exc: BaseException) -> bool:
    """Return true only for transient SQLite lock/busy errors."""

    if not isinstance(exc, OperationalError):
        return False
    message = str(exc).lower()
    return "database is locked" in message or "database is busy" in message


def run_with_sqlite_retry(
    operation: Callable[[], T],
    *,
    attempts: int = 4,
    base_delay_seconds: float = 0.1,
) -> T:
    """Retry a complete idempotent write boundary on transient lock errors."""

    for attempt in range(attempts):
        try:
            return operation()
        except Exception as exc:
            if not is_sqlite_lock_error(exc) or attempt == attempts - 1:
                raise
            time.sleep(base_delay_seconds * (2**attempt))
    raise AssertionError("unreachable")
