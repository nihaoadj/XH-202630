"""Faults during supervision must not abandon a still-running executor."""
from collections import deque
import logging
import sqlite3
from threading import Event, Lock, Thread
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import OperationalError

from app.services.generation.worker import GenerationWorker


class Executions:
    def __init__(self):
        self.pending = deque(["first", "second"])
        self.claimed = []
        self.active = set()
        self.peak = 0
        self.statuses = {}
        self.lock = Lock()
        self.release = Event()
        self.entered = Event()
        self.ended = Event()
        self.recovered = Event()
        self.healthy = Event()
        self.worker = None

    def claim_next(self, owner, lease_seconds):
        if not self.pending:
            return None
        run_id = self.pending.popleft()
        self.claimed.append(run_id)
        self.statuses[run_id] = "running"
        return SimpleNamespace(run_id=run_id, owner=owner, epoch=1)

    def renew_claim(self, claim, lease_seconds):
        return True

    def finish_claim(self, claim, *, error_code=None):
        self.statuses[claim.run_id] = "failed" if error_code else "completed"
        return True

    def get(self, run_id):
        return SimpleNamespace(job_status=self.statuses[run_id])

    def run_claim(self, claim):
        with self.lock:
            self.active.add(claim.run_id)
            self.peak = max(self.peak, len(self.active))
        self.entered.set()
        try:
            if not self.release.wait(10):
                raise TimeoutError("test executor was not released")
            return self.finish_claim(claim)
        finally:
            with self.lock:
                self.active.remove(claim.run_id)
                if not self.active:
                    self.ended.set()
            if claim.run_id == "second":
                self.worker.stop()


@pytest.mark.parametrize(("operation", "locked"), [("renew", True), ("reconcile", True), ("reconcile", False)])
def test_worker_recovers_supervision_errors_without_a_second_execution(operation, locked, caplog):
    executions = Executions()
    worker = GenerationWorker(executions, None, lambda: executions, poll_seconds=.01, lease_seconds=60)
    executions.worker = worker
    remaining = 4 if locked else 1
    renewed_after_failure = False
    observations = []

    def fail_once_per_retry():
        nonlocal remaining
        if remaining:
            remaining -= 1
            if locked:
                raise OperationalError("synthetic statement", {}, sqlite3.OperationalError("database is locked"))
            raise RuntimeError("synthetic reconciliation unavailable")

    def renew(claim, lease_seconds):
        nonlocal renewed_after_failure
        if operation == "renew":
            fail_once_per_retry()
        if remaining == 0:
            renewed_after_failure = True
        return True

    def reconcile():
        if not executions.entered.is_set():
            return {}
        if operation == "reconcile":
            fail_once_per_retry()
        if remaining == 0 and renewed_after_failure:
            # Called on a later successful poll, before its health error clears.
            observations.append(worker.health_snapshot())
            executions.recovered.set()
            if observations[-1]["ready"]:
                executions.healthy.set()
        return {}

    executions.renew_claim = renew
    worker.reconciler.run_once = reconcile
    loop = Thread(target=worker.run_forever, daemon=True)
    with caplog.at_level(logging.ERROR):
        loop.start()
        try:
            assert executions.recovered.wait(5), "worker did not resume supervision"
            assert executions.claimed == ["first"]
            assert executions.peak == 1
            assert any(item["error_code"] == "GENERATION_WORKER_POLL_FAILED" and not item["ready"] for item in observations)
            assert ("OperationalError" if locked else "RuntimeError") in caplog.text
            assert executions.healthy.wait(5), "health did not recover after successful supervision"
            executions.release.set()
            loop.join(5)
            assert executions.ended.wait(5)
            assert not loop.is_alive()
            assert executions.claimed == ["first", "second"]
            assert executions.peak == 1
            assert executions.statuses == {"first": "completed", "second": "completed"}
            assert worker.counts == {"claimed": 2, "processed": 2, "failed": 0}
            assert worker.error_code is None
        finally:
            worker.stop()
            executions.release.set()
            loop.join(5)


def test_persistent_supervision_error_still_honors_shutdown_budget():
    executions = Executions()
    worker = GenerationWorker(executions, None, lambda: executions, poll_seconds=.01, shutdown_seconds=0)
    executions.worker = worker

    def unavailable(claim, lease_seconds):
        worker.stop()
        raise RuntimeError("synthetic unavailable storage")

    executions.renew_claim = unavailable
    worker.reconciler.run_once = lambda: {}
    loop = Thread(target=worker.run_forever, daemon=True)
    loop.start()
    try:
        assert executions.entered.wait(5)
        loop.join(5)
        assert not loop.is_alive()
        assert executions.claimed == ["first"]
        assert executions.active == {"first"}
        health = worker.health_snapshot()
        assert health["active"] and not health["ready"]
        assert health["error_code"] == "GENERATION_WORKER_POLL_FAILED"
    finally:
        worker.stop()
        executions.release.set()
        loop.join(5)
        assert executions.ended.wait(5)


@pytest.mark.parametrize("final_read_fails", [False, True])
def test_lost_lease_keeps_stop_reason_until_executor_finishes(final_read_fails):
    executions = Executions()
    worker = GenerationWorker(executions, None, lambda: executions, poll_seconds=.01)
    executions.worker = worker

    def lost(claim, lease_seconds):
        executions.release.set()
        return False

    executions.renew_claim = lost
    if final_read_fails:
        def unavailable(run_id):
            raise RuntimeError("synthetic final status read unavailable")
        executions.get = unavailable
    worker.reconciler.run_once = lambda: {}
    loop = Thread(target=worker.run_forever, daemon=True)
    loop.start()
    try:
        loop.join(5)
        assert not loop.is_alive()
        assert executions.claimed == ["first"]
        assert worker.health_snapshot()["error_code"] == "GENERATION_WORKER_LEASE_LOST"
        assert not worker.health_snapshot()["ready"]
    finally:
        worker.stop()
        executions.release.set()
        loop.join(5)
        assert executions.ended.wait(5)
