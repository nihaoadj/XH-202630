from __future__ import annotations

from threading import Barrier, Event, Lock, Thread
from time import monotonic, sleep

from app.agents.resource_workflows.interactive_courseware.worker import CoursewareSceneWorker
from app.services.courseware.executor import CoursewareExecutor
from app.db.courseware.repository import MemoryCoursewareRepository


class _Workflow:
    def __init__(self):
        self.calls = 0
        self._lock = Lock()

    def process_scene_outbox(self, *, run_id=None, limit=10):
        with self._lock:
            self.calls += 1
        return {"processed": 0, "approved": 0, "failed": 0, "skipped": 0}


def test_worker_run_once_delegates_to_durable_outbox():
    workflow = _Workflow()
    worker = CoursewareSceneWorker(workflow, poll_interval_seconds=60, batch_size=7)

    result = worker.run_once(run_id="run-1")

    assert result["processed"] == 0
    assert workflow.calls == 1


def test_worker_start_is_reentrant_and_stop_is_bounded():
    workflow = _Workflow()
    worker = CoursewareSceneWorker(workflow, poll_interval_seconds=0.01, batch_size=3)

    worker.start()
    worker.start()
    deadline = monotonic() + 1
    while workflow.calls == 0 and monotonic() < deadline:
        sleep(0.01)
    worker.stop(timeout=1)

    assert workflow.calls > 0
    assert worker._thread is None


def test_memory_scene_lease_has_one_winner_under_concurrency():
    repo = MemoryCoursewareRepository()
    repo.upsert_scene({
        "scene_id": "scene-1", "spec_id": "spec-1", "scene_order": 0,
        "kind": "intro", "scene_json": {}, "content_hash": "hash-1",
        "status": "revision_required", "attempt": 1,
    })
    barrier = Barrier(2)
    results = []

    def claim(owner: str) -> None:
        barrier.wait()
        results.append(repo.claim_scene("scene-1", owner, lease_seconds=60))

    threads = [Thread(target=claim, args=(f"worker-{index}",)) for index in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=1)

    winners = [item for item in results if item is not None]
    assert len(winners) == 1
    assert winners[0]["lease_owner"] in {"worker-0", "worker-1"}


def test_durable_executor_claims_and_completes_initial_run_task():
    repo = MemoryCoursewareRepository()
    repo.create_job({
        "run_id": "run-1", "learner_id": "learner-1", "request_hash": "hash-1",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-1", "run_id": "run-1", "event_type": "courseware.run",
        "idempotency_key": "task-1", "payload": {},
    })

    class Workflow:
        def __init__(self):
            self.calls = []
            self.repo = repo

        def run(self, run_id):
            self.calls.append(run_id)
            repo.update_job(run_id, status="published")

    workflow = Workflow()
    result = CoursewareExecutor(repo, workflow, owner_id="worker-1", lease_seconds=30).run_once()

    assert result == {"claimed": 1, "processed": 1, "failed": 0}
    assert workflow.calls == ["run-1"]
    assert repo.list_outbox(pending_only=False)[0]["status"] == "complete"


def test_durable_executor_exposes_safe_readiness_and_claim_metrics():
    """The standalone Worker must be observable without exposing task payloads."""
    repo = MemoryCoursewareRepository()
    repo.create_job({
        "run_id": "run-health", "learner_id": "learner-health", "request_hash": "hash-health",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-health", "run_id": "run-health", "event_type": "courseware.run",
        "idempotency_key": "task-health", "payload": {"sensitive": "must-not-appear"},
    })

    class Workflow:
        def run(self, _run_id):
            return None

    executor = CoursewareExecutor(repo, Workflow(), owner_id="health-worker")
    before = executor.health_snapshot()
    assert before["ready"] is False
    assert "payload" not in before

    result = executor.run_once()
    after = executor.health_snapshot()

    assert result == {"claimed": 1, "processed": 1, "failed": 0}
    assert after["ready"] is True
    assert after["metrics"]["claim_count"] == 1
    assert after["metrics"]["processed_count"] == 1
    assert {"retry_count", "fallback_count", "quarantine_count", "release_count"} <= set(after["metrics"])
    assert "payload" not in str(after)


def test_unstarted_claim_in_batch_never_expires_while_previous_task_runs():
    """A sequential durable Worker must not lease work it cannot yet heartbeat."""
    repo = MemoryCoursewareRepository()
    for index in (1, 2):
        run_id = f"batch-run-{index}"
        repo.create_job({"run_id": run_id, "learner_id": "learner", "request_hash": run_id,
                         "source_resource_ids": [], "source_snapshots": [], "status": "queued"})
        repo.enqueue_task_once({"outbox_id": f"batch-task-{index}", "run_id": run_id,
                                "event_type": "courseware.run", "idempotency_key": f"batch-task-{index}", "payload": {}})
    started = Event()

    class SlowWorkflow:
        def run(self, _run_id):
            started.set()
            sleep(2.2)

    executor = CoursewareExecutor(repo, SlowWorkflow(), owner_id="first-owner", batch_size=2, lease_seconds=1)
    worker = Thread(target=executor.run_once)
    worker.start()
    assert started.wait(timeout=1)
    sleep(1.2)
    before = {row["outbox_id"]: row for row in repo.list_outbox(pending_only=False)}
    stolen = repo.claim_task_batch("second-owner", limit=2, lease_seconds=1)
    worker.join(timeout=5)

    assert before["batch-task-1"]["claimed_by"] == "first-owner"
    assert before["batch-task-2"]["status"] == "queued"
    assert [(row["outbox_id"], row["attempt"]) for row in stolen] == [("batch-task-2", 1)]
