"""Durable courseware task executor used by the standalone Worker process."""

from __future__ import annotations

import logging
import os
import socket
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)


class CoursewareLeaseLost(RuntimeError):
    """Raised when a worker can no longer prove ownership of its outbox task."""


class CoursewareExecutor:
    def __init__(self, repo, workflow, *, poll_interval_seconds: float = 2.0,
                 batch_size: int = 10, lease_seconds: int = 120,
                 owner_id: str | None = None):
        self.repo = repo
        self.workflow = workflow
        self.poll_interval_seconds = poll_interval_seconds
        # The supported SQLite topology is one sequential durable Worker.  A
        # larger pre-claim batch lets later tasks expire before their own
        # heartbeat starts, so normalize it rather than claiming unsafe work.
        if int(batch_size) != 1:
            logger.warning("courseware Worker batch size normalized to one for SQLite durable safety configured=%s", batch_size)
        self.batch_size = 1
        self.lease_seconds = lease_seconds
        self.owner_id = owner_id or f"cw-worker:{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"
        self._stop = threading.Event()
        self._metrics_lock = threading.Lock()
        self._started_at: datetime | None = None
        self._last_poll_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_error_code: str | None = None
        self._has_completed_poll = False
        self._metrics = {
            "claim_count": 0,
            "processed_count": 0,
            "failed_count": 0,
            "lease_lost_count": 0,
            "retry_count": 0,
            "fallback_count": 0,
            "quarantine_count": 0,
            "release_count": 0,
            "poll_count": 0,
        }

    def health_snapshot(self) -> dict[str, object]:
        """Return deployment-safe Worker liveness/readiness and counters.

        This deliberately contains no run IDs, task payloads, database URL, or
        provider information.  A completed durable-outbox poll demonstrates
        that the process can claim against its configured repository; the
        readiness probe can therefore distinguish booting from a usable worker.
        """
        with self._metrics_lock:
            running = self._started_at is not None and not self._stop.is_set()
            return {
                "status": "ready" if self._has_completed_poll and running else "starting" if running else "stopped",
                "live": running,
                "ready": bool(self._has_completed_poll and running),
                "owner_id": self.owner_id,
                "started_at": self._started_at.isoformat() if self._started_at else None,
                "last_poll_at": self._last_poll_at.isoformat() if self._last_poll_at else None,
                "last_success_at": self._last_success_at.isoformat() if self._last_success_at else None,
                "last_error_code": self._last_error_code,
                "metrics": dict(self._metrics),
            }

    def run_once(self, limit: int | None = None) -> dict[str, int]:
        started_at = datetime.now(timezone.utc)
        with self._metrics_lock:
            if self._started_at is None:
                self._started_at = started_at
        claimed = self.repo.claim_task_batch(
            self.owner_id, now=datetime.now(timezone.utc), limit=max(1, min(int(limit or self.batch_size), self.batch_size)),
            lease_seconds=self.lease_seconds,
        )
        processed = failed = 0
        retry_count = fallback_count = quarantine_count = release_count = 0
        for task in claimed:
            heartbeat_stop = threading.Event()
            lease_lost = threading.Event()
            heartbeat = threading.Thread(
                target=self._heartbeat, args=(task["outbox_id"], heartbeat_stop, lease_lost),
                name=f"courseware-heartbeat-{task['outbox_id']}", daemon=True,
            )
            heartbeat.start()
            try:
                if hasattr(self.workflow, "set_lease_lost_event"):
                    self.workflow.set_lease_lost_event(lease_lost)
                job = self.repo.get_job(task["run_id"])
                deadline = job.get("deadline_at") if job else None
                if deadline is not None and deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=timezone.utc)
                if job and job.get("status") == "cancelled":
                    self.repo.complete_task(task["outbox_id"], self.owner_id)
                    processed += 1
                    continue
                if deadline and deadline <= datetime.now(timezone.utc):
                    self.repo.update_job(
                        task["run_id"], status="timed_out", error_code="COURSEWARE_RUN_TIMEOUT",
                        error_message="课件任务超过总时限",
                    )
                    self.workflow._event(task["run_id"], "job", "timed_out", {"error_code": "COURSEWARE_RUN_TIMEOUT"})
                    self.repo.complete_task(task["outbox_id"], self.owner_id)
                    processed += 1
                    continue
                if lease_lost.is_set():
                    raise CoursewareLeaseLost("课件任务租约已失效")
                if task.get("scene_id"):
                    scene = self.workflow.repo.get_scene(task["scene_id"])
                    self.workflow.retry_scene(
                        task["run_id"], task["scene_id"],
                        review_instruction=(task.get("payload") or {}).get("review_instruction")
                        or (scene or {}).get("review_instruction"),
                        automatic=True, enqueue_outbox=False,
                    )
                else:
                    self.workflow.run(task["run_id"])
                if lease_lost.is_set():
                    raise CoursewareLeaseLost("课件任务租约已失效")
                terminal = self.repo.get_job(task["run_id"]) or {}
                retry_count += int(task.get("attempt") or 0) > 1
                warnings = terminal.get("warnings") or []
                fallback_count += any(
                    isinstance(item, dict) and item.get("fallback_version")
                    for item in warnings
                ) or "FALLBACK" in str(terminal.get("error_code") or "")
                quarantine_count += terminal.get("status") == "quarantined"
                release_count += terminal.get("status") in {"published", "stale"} and bool(
                    terminal.get("released_release_id")
                )
                self.repo.complete_task(task["outbox_id"], self.owner_id)
                processed += 1
            except Exception as exc:  # task boundary: persist failure, keep worker alive
                logger.exception("courseware task failed outbox_id=%s", task["outbox_id"])
                failed_task = self.repo.fail_task(task["outbox_id"], self.owner_id, exc)
                if failed_task and failed_task.get("status") == "dead_lettered":
                    self.repo.update_job(
                        task["run_id"], status="failed", error_code="COURSEWARE_TASK_DEAD_LETTERED",
                        error_message="课件任务达到最大重试次数后进入死信",
                    )
                    self.workflow._event(task["run_id"], "job", "dead_lettered", {
                        "error_code": "COURSEWARE_TASK_DEAD_LETTERED",
                    })
                failed += 1
                if isinstance(exc, CoursewareLeaseLost):
                    with self._metrics_lock:
                        self._metrics["lease_lost_count"] += 1
            finally:
                heartbeat_stop.set()
                heartbeat.join(timeout=1.0)
        with self._metrics_lock:
            self._last_poll_at = started_at
            self._has_completed_poll = True
            self._metrics["poll_count"] += 1
            self._metrics["claim_count"] += len(claimed)
            self._metrics["processed_count"] += processed
            self._metrics["failed_count"] += failed
            self._metrics["retry_count"] += retry_count
            self._metrics["fallback_count"] += fallback_count
            self._metrics["quarantine_count"] += quarantine_count
            self._metrics["release_count"] += release_count
            if failed:
                self._last_error_code = "COURSEWARE_TASK_FAILED"
            else:
                self._last_success_at = datetime.now(timezone.utc)
                self._last_error_code = None
        return {"claimed": len(claimed), "processed": processed, "failed": failed}

    def _heartbeat(self, outbox_id: str, stop: threading.Event, lease_lost: threading.Event | None = None) -> None:
        # Renew well before a short injected lease can expire. Production
        # settings use a longer lease, while the bounded lower floor keeps
        # fault tests deterministic without creating a busy loop.
        interval = max(0.05, min(1.0, self.lease_seconds / 3))
        while not stop.wait(interval):
            expires_at = datetime.now(timezone.utc) + timedelta(seconds=self.lease_seconds)
            if self.repo.renew_task_lease(outbox_id, self.owner_id, expires_at) is None:
                if lease_lost is not None:
                    lease_lost.set()
                return

    def run_forever(self) -> None:
        with self._metrics_lock:
            self._started_at = datetime.now(timezone.utc)
        try:
            while not self._stop.is_set():
                started = time.monotonic()
                try:
                    self.run_once()
                except Exception:
                    logger.exception("courseware executor iteration failed")
                    with self._metrics_lock:
                        self._last_poll_at = datetime.now(timezone.utc)
                        self._last_error_code = "COURSEWARE_WORKER_POLL_FAILED"
                        self._metrics["poll_count"] += 1
                        self._metrics["failed_count"] += 1
                self._stop.wait(max(0.0, self.poll_interval_seconds - (time.monotonic() - started)))
        finally:
            # Liveness intentionally turns false only after the run loop has
            # stopped, letting SIGTERM finish the currently claimed task.
            self._stop.set()

    def stop(self) -> None:
        self._stop.set()
