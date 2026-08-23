"""Recoverable scene-retry worker for the interactive-courseware domain."""

from __future__ import annotations

import logging
from threading import Event, Thread
from time import monotonic

logger = logging.getLogger(__name__)

class CoursewareSceneWorker:
    """Drain persisted retry intents without owning prompts or rendering."""

    def __init__(self, workflow, poll_interval_seconds: float = 2.0, batch_size: int = 10):
        self.workflow = workflow
        self.poll_interval_seconds = poll_interval_seconds
        self.batch_size = batch_size
        self._stop = Event()
        self._thread: Thread | None = None

    def run_once(self, run_id: str | None = None, limit: int = 10) -> dict[str, int]:
        return self.workflow.process_scene_outbox(run_id=run_id, limit=limit)

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self.run_forever, name="courseware-scene-worker", daemon=True)
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)
        self._thread = None

    def run_forever(self) -> None:
        """Poll the durable outbox until application shutdown."""
        while not self._stop.is_set():
            started = monotonic()
            try:
                self.run_once(limit=self.batch_size)
            except Exception:
                logger.exception("courseware scene worker iteration failed")
            remaining = max(0.0, self.poll_interval_seconds - (monotonic() - started))
            self._stop.wait(remaining)
