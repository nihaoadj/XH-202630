"""C1 file-SQLite fault cases: every worker action runs in a spawned process."""

from __future__ import annotations

import multiprocessing
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from socket import socket
from urllib.request import urlopen

from sqlalchemy import create_engine
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker

from app.db.courseware.models import Base, CoursewareReleaseORM
from app.db.courseware.repository import SQLCoursewareRepository
from app.db.shared.models import LearnerProfileORM
from app.services.courseware.executor import CoursewareExecutor
from app.services.courseware.release import CandidateReleaseCoordinator


def _child_worker(database_path: str, action: str, ready, result) -> None:
    """A real process-local executor with a deterministic, zero-model workflow."""
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False, "timeout": 5})
    repo = SQLCoursewareRepository(sessionmaker(bind=engine))

    class Workflow:
        def __init__(self):
            self.repo = repo
            self.lease_lost = None

        def set_lease_lost_event(self, event):
            self.lease_lost = event

        def run(self, run_id):
            repo.save_checkpoint_once({"checkpoint_id": f"cp-{run_id}", "run_id": run_id,
                                       "stage": "process_checkpoint", "attempt": 1,
                                       "state_json": {"process": os.getpid()}, "input_hash": "a" * 64,
                                       "output_hash": "b" * 64, "workflow_version": "c1-process-v1"})
            ready.put({"pid": os.getpid(), "run_id": run_id, "action": action})
            if action == "crash_after_checkpoint":
                os._exit(86)
            if action == "hold_claim":
                time.sleep(30)
            if action == "heartbeat_lost":
                time.sleep(2.0)
            repo.update_job(run_id, status="completed_by_process")

        def _event(self, *_args, **_kwargs):
            return None

    executor = CoursewareExecutor(repo, Workflow(), owner_id=f"c1-child:{os.getpid()}", lease_seconds=1, batch_size=1)
    try:
        outcome = executor.run_once()
        result.put({"pid": os.getpid(), "exit": 0, "outcome": outcome, "health": executor.health_snapshot()})
    except BaseException as exc:
        result.put({"pid": os.getpid(), "exit": 1, "error": type(exc).__name__})
        raise


def _repo(tmp_path, *, enqueue: bool = True, path: Path | None = None):
    path = path or tmp_path / "c1-process.db"
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False, "timeout": 5})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(learner_id="c1-learner", learner_type="test", education="test", major="test", learning_goal="test", skill_level="test"))
        db.commit()
    repo = SQLCoursewareRepository(factory)
    repo.create_job({"run_id": "c1-run", "learner_id": "c1-learner", "request_hash": "c1-hash", "source_resource_ids": [], "source_snapshots": [], "status": "queued"})
    repo.save_resource({"resource_id": "resource-a7", "resource_family_id": "resource-a7", "run_id": "c1-run",
                       "learner_id": "c1-learner", "title": "C1", "topic": "故障验收", "status": "building",
                       "version": 1, "file_path": "candidate", "file_size": 1, "artifact_sha256": "old",
                       "renderer_version": "r1", "runtime_version": "rt1", "source_summary": [], "warnings": []}, [])
    if enqueue:
        repo.enqueue_task_once({"outbox_id": "c1-task", "run_id": "c1-run", "event_type": "courseware.run", "idempotency_key": "c1-task", "payload": {}})
    return path, repo


def _release_status(repo, release_id: str) -> str:
    with repo.session_factory() as db:
        return db.get(CoursewareReleaseORM, release_id).status


def _spawn(path, action):
    context = multiprocessing.get_context("spawn")
    ready, result = context.Queue(), context.Queue()
    process = context.Process(target=_child_worker, args=(str(path), action, ready, result))
    process.start()
    return process, ready, result


def _claim_only(database_path: str, owner: str, result) -> None:
    engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False, "timeout": 5})
    repo = SQLCoursewareRepository(sessionmaker(bind=engine))
    claimed = repo.claim_task_batch(owner, datetime.now(timezone.utc), 1, lease_seconds=30)
    result.put({"owner": owner, "claimed": len(claimed), "claimed_by": claimed[0].get("claimed_by") if claimed else None})


def _candidate_child(database_path: str, action: str, result) -> None:
    try:
        engine = create_engine(f"sqlite:///{database_path}", connect_args={"check_same_thread": False, "timeout": 5})
        repo = SQLCoursewareRepository(sessionmaker(bind=engine))
        coordinator = CandidateReleaseCoordinator(repo)
        first = coordinator.freeze(
            run_id="c1-run", resource_id="resource-a7", release_policy="resilient",
            snapshots=[{"resource_id": "source", "version": 1, "content_hash": "source-hash"}],
            scenes=[{"scene_id": "scene", "scene_order": 0, "content_hash": "scene-hash", "revision_no": 1}],
            provenance={"root_hash": "root"},
        )
        if action == "artifact_before_release":
            repo.save_artifact({
                "artifact_id": "artifact-before-release", "courseware_resource_id": "resource-a7",
                "release_id": first["release_id"], "artifact_format": "html", "file_path": "candidate/index.html",
                "mime_type": "text/html", "file_size": 1, "sha256": "a" * 64,
                "manifest": {}, "required": 1, "artifact_status": "ready",
            })
            result.put({"release_id": first["release_id"], "action": action})
            return
        if action == "release_commit_failure":
            blocked = coordinator.block(first, code="RELEASE_COMMIT_FAILED", message="injected commit failure")
            result.put({"release_id": first["release_id"], "status": blocked["status"] if blocked else None})
            return
        if action == "failed_candidate_keeps_release":
            committed = coordinator.commit(
                first, resource_id="resource-a7",
                resource_projection={"file_path": "first", "file_size": 1, "artifact_sha256": "b" * 64},
                job_status="published", warnings=[],
                event_payload={"event_id": "c1-release-first", "run_id": "c1-run", "payload": {"release_id": first["release_id"]}},
            )
            second = coordinator.freeze(
                run_id="c1-run", resource_id="resource-a7", release_policy="resilient",
                snapshots=[{"resource_id": "source", "version": 2, "content_hash": "source-new"}],
                scenes=[{"scene_id": "scene", "scene_order": 0, "content_hash": "scene-new", "revision_no": 2}],
                provenance={"root_hash": "root-new"},
            )
            blocked = coordinator.block(second, code="REQUIRED_ARTIFACT_FAILED", message="zip failed")
            result.put({"first_release_id": committed["release_id"] if committed else None,
                        "second_release_id": second["release_id"], "second_status": blocked["status"] if blocked else None})
    except BaseException as exc:
        result.put({"error": type(exc).__name__, "message": str(exc)})
        raise


def _spawn_claim(path: Path, owner: str):
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=_claim_only, args=(str(path), owner, result))
    process.start()
    return process, result


def _spawn_candidate(path: Path, action: str):
    context = multiprocessing.get_context("spawn")
    result = context.Queue()
    process = context.Process(target=_candidate_child, args=(str(path), action, result))
    process.start()
    return process, result


def test_c1_process_worker_kill_then_lease_takeover_and_checkpoint_recovery(tmp_path):
    path, repo = _repo(tmp_path)
    worker, ready, _result = _spawn(path, "hold_claim")
    observed = ready.get(timeout=10)
    assert observed["run_id"] == "c1-run" and observed["pid"] == worker.pid
    claimed = repo.list_outbox("c1-run", pending_only=False)[0]
    assert claimed["status"] == "claimed" and claimed["claimed_by"] == f"c1-child:{worker.pid}"
    assert repo.latest_checkpoint("c1-run")["stage"] == "process_checkpoint"
    worker.terminate(); worker.join(timeout=10)
    assert worker.exitcode is not None and worker.exitcode != 0
    assert repo.claim_task_batch("second-before-expiry", datetime.now(timezone.utc), 1, lease_seconds=1) == []
    time.sleep(1.2)
    restarted, _ready, result = _spawn(path, "resume")
    restarted.join(timeout=10)
    assert restarted.exitcode == 0
    outcome = result.get(timeout=2)
    task = repo.list_outbox("c1-run", pending_only=False)[0]
    assert outcome["outcome"]["processed"] == 1
    assert task["status"] == "complete" and task["attempt"] == 2
    assert repo.latest_checkpoint("c1-run")["output_hash"] == "b" * 64


def test_c1_process_checkpoint_crash_is_replayed_once_without_duplicate_side_effect(tmp_path):
    path, repo = _repo(tmp_path)
    crashed, _ready, _result = _spawn(path, "crash_after_checkpoint")
    crashed.join(timeout=10)
    assert crashed.exitcode == 86
    assert repo.latest_checkpoint("c1-run")["stage"] == "process_checkpoint"
    time.sleep(1.2)
    recovered, _ready, result = _spawn(path, "resume")
    recovered.join(timeout=10)
    assert recovered.exitcode == 0 and result.get(timeout=2)["outcome"]["processed"] == 1
    assert len(repo.list_events("c1-run")) == 0
    assert repo.list_outbox("c1-run", pending_only=False)[0]["attempt"] == 2


def test_c1_process_sqlite_busy_waits_then_has_one_claim_winner(tmp_path):
    path, repo = _repo(tmp_path)
    holder = create_engine(f"sqlite:///{path.as_posix()}").connect()
    holder.exec_driver_sql("BEGIN IMMEDIATE")
    worker, _ready, result = _spawn(path, "resume")
    time.sleep(0.2)
    assert worker.is_alive()
    holder.commit(); holder.close()
    worker.join(timeout=10)
    assert worker.exitcode == 0 and result.get(timeout=2)["outcome"]["claimed"] == 1
    assert repo.list_outbox("c1-run", pending_only=False)[0]["status"] == "complete"


def test_c1_process_heartbeat_loss_stops_owner_and_allows_expired_lease_recovery(tmp_path):
    path, repo = _repo(tmp_path)
    worker, ready, result = _spawn(path, "heartbeat_lost")
    assert ready.get(timeout=10)["pid"] == worker.pid
    # Simulate loss of the Worker-owned lease from a separate SQLite client;
    # the running child must discover it through the real renewal CAS.
    engine = create_engine(f"sqlite:///{path.as_posix()}")
    with engine.begin() as db:
        db.execute(text("UPDATE courseware_outbox SET claimed_by = :owner WHERE outbox_id = :task"), {"owner": "lost-owner", "task": "c1-task"})
    worker.join(timeout=10)
    observation = result.get(timeout=2)
    assert worker.exitcode == 0
    assert observation["outcome"]["failed"] == 1
    assert observation["health"]["metrics"]["lease_lost_count"] == 1
    time.sleep(1.2)
    replacement, _ready, replacement_result = _spawn(path, "resume")
    replacement.join(timeout=10)
    assert replacement.exitcode == 0
    assert replacement_result.get(timeout=2)["outcome"]["processed"] == 1
    assert repo.list_outbox("c1-run", pending_only=False)[0]["attempt"] == 2


def test_c1_process_safe_backup_and_restored_worker_start(tmp_path):
    source, repo = _repo(tmp_path, enqueue=False)
    repo.save_checkpoint_once({"checkpoint_id": "cp-backup", "run_id": "c1-run", "stage": "backup",
                               "attempt": 1, "state_json": {}, "input_hash": "c" * 64,
                               "output_hash": "d" * 64, "workflow_version": "c1-process-v1"})
    restored = tmp_path / "restored.db"
    root = __import__("pathlib").Path(__file__).resolve().parents[4]
    backup = subprocess.run([sys.executable, "backend/scripts/courseware_sqlite_backup.py", "--source", str(source),
                             "--output", str(restored), "--writes-stopped"], cwd=root, capture_output=True, text=True)
    assert backup.returncode == 0 and restored.is_file()
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "DB_TYPE": "sqlite",
           "DATABASE_URL": f"sqlite:///{restored.as_posix()}", "COURSEWARE_AI_ENABLED": "false"}
    worker = subprocess.run([sys.executable, "backend/scripts/courseware_worker.py", "--once"], cwd=root, env=env,
                            capture_output=True, text=True, timeout=20)
    assert worker.returncode == 0
    restored_repo = SQLCoursewareRepository(sessionmaker(bind=create_engine(f"sqlite:///{restored.as_posix()}")))
    assert restored_repo.latest_checkpoint("c1-run")["output_hash"] == "d" * 64
    assert restored_repo.list_outbox("c1-run", pending_only=False) == []


def test_c1_process_sqlite_temporary_disconnect_then_fresh_worker_recovers(tmp_path):
    """A Worker process must report a real unavailable SQLite file, then recover.

    The first independent process gets an empty file without the durable
    schema (a transient mounted-file/disconnect equivalent).  We then restore
    the schema/data and prove a fresh independent Worker claims it exactly
    once; this is deliberately not a same-process mock or retry shim.
    """
    path = tmp_path / "temporarily-unavailable.db"
    first, _ready, result = _spawn(path, "resume")
    first.join(timeout=10)
    assert first.exitcode is not None and first.exitcode != 0
    assert result.get(timeout=2)["error"] == "OperationalError"
    _path, repo = _repo(tmp_path, path=path)
    recovered, _ready, recovered_result = _spawn(path, "resume")
    recovered.join(timeout=10)
    assert recovered.exitcode == 0
    assert recovered_result.get(timeout=2)["outcome"] == {"claimed": 1, "processed": 1, "failed": 0}
    task = repo.list_outbox("c1-run", pending_only=False)[0]
    assert task["status"] == "complete" and task["attempt"] == 1 and task["claimed_by"].startswith("c1-child:")


def _free_port() -> int:
    with socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def test_c1_process_worker_script_handles_graceful_shutdown(tmp_path):
    """The standalone Worker process exposes ready, then drains on an external stop request."""
    path, _repo_instance = _repo(tmp_path, enqueue=False)
    root = Path(__file__).resolve().parents[4]
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(root / "backend"), "DB_TYPE": "sqlite",
           "DATABASE_URL": f"sqlite:///{path.as_posix()}", "COURSEWARE_AI_ENABLED": "false",
           "COURSEWARE_WORKER_POLL_INTERVAL_SECONDS": "0.05"}
    shutdown_file = tmp_path / "graceful-stop"
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    worker = subprocess.Popen([sys.executable, "backend/scripts/courseware_worker.py", "--health-port", str(port),
                               "--shutdown-file", str(shutdown_file)],
                              cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                              creationflags=flags)
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            try:
                with urlopen(f"http://127.0.0.1:{port}/health/ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise AssertionError("worker did not become ready")
        shutdown_file.touch()
        assert worker.wait(timeout=10) == 0
    finally:
        if worker.poll() is None:
            worker.kill()
            worker.wait(timeout=10)


def test_c1_process_duplicate_delivery_has_one_outbox_effective_task(tmp_path):
    path, repo = _repo(tmp_path)
    first, _ready, first_result = _spawn(path, "resume")
    first.join(timeout=10)
    assert first.exitcode == 0 and first_result.get(timeout=2)["outcome"]["processed"] == 1
    repo.enqueue_task_once({"outbox_id": "c1-task-replay", "run_id": "c1-run", "event_type": "courseware.run",
                            "idempotency_key": "c1-task", "payload": {}})
    second, _ready, second_result = _spawn(path, "resume")
    second.join(timeout=10)
    assert second.exitcode == 0 and second_result.get(timeout=2)["outcome"] == {"claimed": 0, "processed": 0, "failed": 0}
    tasks = repo.list_outbox("c1-run", pending_only=False)
    assert len(tasks) == 1 and tasks[0]["status"] == "complete" and tasks[0]["attempt"] == 1


def test_c1_process_unexpected_concurrent_claim_has_one_winner(tmp_path):
    path, repo = _repo(tmp_path)
    first, first_result = _spawn_claim(path, "claim-a")
    second, second_result = _spawn_claim(path, "claim-b")
    first.join(timeout=10); second.join(timeout=10)
    assert first.exitcode == 0 and second.exitcode == 0
    observations = [first_result.get(timeout=2), second_result.get(timeout=2)]
    assert sorted(item["claimed"] for item in observations) == [0, 1]
    task = repo.list_outbox("c1-run", pending_only=False)[0]
    assert task["status"] == "claimed" and task["claimed_by"] in {"claim-a", "claim-b"} and task["attempt"] == 1


def test_c1_process_artifact_before_release_commit_has_no_release_pointer(tmp_path):
    path, repo = _repo(tmp_path)
    process, result = _spawn_candidate(path, "artifact_before_release")
    process.join(timeout=10)
    assert process.exitcode == 0
    observation = result.get(timeout=2)
    assert repo.get_resource("resource-a7")["released_release_id"] is None
    assert _release_status(repo, observation["release_id"]) == "building"
    artifact = repo.list_artifacts("resource-a7")[0]
    assert artifact["release_id"] == observation["release_id"] and artifact["sha256"] == "a" * 64


def test_c1_process_release_commit_failure_blocks_candidate_without_pointer(tmp_path):
    path, repo = _repo(tmp_path)
    process, result = _spawn_candidate(path, "release_commit_failure")
    process.join(timeout=10)
    assert process.exitcode == 0
    observation = result.get(timeout=2)
    assert observation["status"] == "blocked"
    assert repo.get_resource("resource-a7")["released_release_id"] is None
    assert repo.get_job("c1-run")["status"] == "release_blocked"


def test_c1_process_outbox_replay_keeps_one_delivered_row(tmp_path):
    path, repo = _repo(tmp_path)
    first, _ready, result = _spawn(path, "resume")
    first.join(timeout=10)
    assert first.exitcode == 0 and result.get(timeout=2)["outcome"]["processed"] == 1
    replay = repo.enqueue_task_once({"outbox_id": "c1-replay-id", "run_id": "c1-run", "event_type": "courseware.run",
                                     "idempotency_key": "c1-task", "payload": {}})
    assert replay["status"] == "complete" and replay["attempt"] == 1
    assert len(repo.list_outbox("c1-run", pending_only=False)) == 1


def test_c1_process_scene_retry_replay_has_one_scene_revision(tmp_path):
    path, repo = _repo(tmp_path, enqueue=False)
    repo.save_spec({"spec_id": "c1-spec", "run_id": "c1-run", "schema_version": "1.0", "prompt_version": "c1",
                    "runtime_version": "1.0", "spec_json": {}, "content_hash": "c" * 64, "status": "approved"})
    repo.upsert_scene({"scene_id": "c1-scene", "spec_id": "c1-spec", "scene_order": 0, "kind": "intro",
                       "scene_json": {}, "content_hash": "d" * 64, "status": "approved", "attempt": 1,
                       "input_snapshot_hash": "e" * 64, "agent_version": "c1", "prompt_version": "c1"})
    row = {"revision_id": "c1-revision", "scene_id": "c1-scene", "revision_no": 1, "trigger": "retry",
           "actor_id": "c1-worker", "reason": "replay", "before_content_hash": "d" * 64,
           "after_content_hash": "f" * 64, "input_snapshot_hash": "e" * 64, "idempotency_key": "c1-scene-retry"}
    repo.save_scene_revision_once(row)
    repo.save_scene_revision_once({**row, "after_content_hash": "0" * 64})
    revisions = repo.list_scene_revisions("c1-scene")
    assert len(revisions) == 1 and revisions[0]["after_content_hash"] == "f" * 64


def test_c1_process_failed_candidate_keeps_previous_release_pointer(tmp_path):
    path, repo = _repo(tmp_path)
    process, result = _spawn_candidate(path, "failed_candidate_keeps_release")
    process.join(timeout=10)
    assert process.exitcode == 0
    observation = result.get(timeout=2)
    resource = repo.get_resource("resource-a7")
    assert observation["first_release_id"] == resource["released_release_id"]
    assert observation["second_status"] == "blocked"
    assert _release_status(repo, observation["first_release_id"]) == "released"
    assert _release_status(repo, observation["second_release_id"]) == "blocked"
