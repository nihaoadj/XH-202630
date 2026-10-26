"""Single-concurrency durable text execution with a live reconciliation loop."""
import logging
import threading
import time
import uuid

from app.db.shared.retry import run_with_sqlite_retry
from app.services.generation.reconciliation import GenerationReconciler

logger = logging.getLogger(__name__)


class GenerationWorker:
    def __init__(self, jobs, feedback, service_factory, *, lease_seconds=1260,
                 poll_seconds=2.0, shutdown_seconds=30.0, queued_timeout_seconds=1260,
                 ready=lambda: True, curriculum=None):
        self.jobs = jobs
        self.service_factory = service_factory
        self.reconciler = GenerationReconciler(jobs, feedback, queued_timeout_seconds, curriculum=curriculum)
        self.lease_seconds = lease_seconds
        self.poll_seconds = poll_seconds
        self.shutdown_seconds = shutdown_seconds
        self.ready = ready
        self.owner = f"text-worker-{uuid.uuid4()}"
        self._stop = threading.Event()
        self._stop_at = None
        self._last_tick = time.monotonic()
        self._active = False
        self.counts = {"claimed": 0, "processed": 0, "failed": 0}
        self.error_code = None

    def stop(self):
        if not self._stop.is_set():
            self._stop_at = time.monotonic()
            self._stop.set()

    def reconcile(self):
        result = run_with_sqlite_retry(self.reconciler.run_once)
        self._last_tick = time.monotonic()
        return result

    def run_once(self):
        self.reconcile()
        result = {"claimed": 0, "processed": 0, "failed": 0}
        if self._stop.is_set() or not self.ready():
            return result
        claim = run_with_sqlite_retry(lambda: self.jobs.claim_next(self.owner, self.lease_seconds))
        if claim is None:
            return result
        result["claimed"] = 1
        self.counts["claimed"] += 1
        self._active = True
        outcome = []

        def execute():
            try:
                outcome.append(bool(self.service_factory().run_claim(claim)))
            except Exception as exc:
                logger.error("Generation executor failed run_id=%s epoch=%s type=%s",
                             claim.run_id, claim.epoch, type(exc).__name__)
                self.jobs.finish_claim(claim, error_code="GENERATION_EXECUTOR_UNAVAILABLE")
                outcome.append(False)

        thread = threading.Thread(target=execute, name="generation-task", daemon=True)
        thread.start()
        lost = False
        while thread.is_alive():
            thread.join(timeout=min(self.poll_seconds, max(0.1, self.lease_seconds / 3)))
            if thread.is_alive():
                operation = "renew_claim"
                try:
                    renewed = run_with_sqlite_retry(lambda: self.jobs.renew_claim(claim, self.lease_seconds))
                    if not renewed and not lost:
                        lost = True
                        self.error_code = "GENERATION_WORKER_LEASE_LOST"
                        logger.error("Generation claim lost run_id=%s epoch=%s", claim.run_id, claim.epoch)
                        self.stop()
                    operation = "reconcile"
                    self.reconcile()
                except Exception as exc:
                    # Keep supervising this executor: returning to the poll
                    # loop would allow another claim while it is still alive.
                    if not lost:
                        self.error_code = "GENERATION_WORKER_POLL_FAILED"
                    logger.error("Generation worker supervision failed run_id=%s epoch=%s operation=%s type=%s",
                                 claim.run_id, claim.epoch, operation, type(exc).__name__)
                else:
                    if not lost:
                        self.error_code = None
            if self._stop_at is not None and time.monotonic() - self._stop_at >= self.shutdown_seconds:
                # Do not transfer an executing run. Its persisted lease will expire.
                return result
        self._active = False
        job = self.jobs.get(claim.run_id)
        result["processed" if job and job.job_status == "completed" else "failed"] = 1
        for key in ("processed", "failed"):
            self.counts[key] += result[key]
        self._last_tick = time.monotonic()
        return result

    def run_forever(self):
        while not self._stop.is_set():
            try:
                self.run_once()
                if not self._stop.is_set():
                    self.error_code = None
            except Exception as exc:
                if self.error_code != "GENERATION_WORKER_LEASE_LOST":
                    self.error_code = "GENERATION_WORKER_POLL_FAILED"
                logger.error("Generation worker poll failed type=%s", type(exc).__name__)
            self._stop.wait(self.poll_seconds)

    def health_snapshot(self):
        live = time.monotonic() - self._last_tick < max(30.0, self.poll_seconds * 5)
        try:
            can_execute = bool(self.ready())
        except Exception:
            can_execute = False
        ready = live and can_execute and not self._stop.is_set() and self.error_code is None
        return {"live": live, "ready": ready,
                "status": "stopping" if self._stop.is_set() else "ready" if ready else "not_ready",
                "active": self._active, "concurrency": 1, "error_code": self.error_code, **self.counts}
