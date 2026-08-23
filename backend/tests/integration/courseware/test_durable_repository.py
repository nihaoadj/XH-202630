from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import time
import multiprocessing

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.courseware.models import Base
from app.db.courseware.repository import SQLCoursewareRepository
from app.db.shared.models import LearnerProfileORM


def _claim_from_independent_process(database_path: str, owner: str):
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    factory = sessionmaker(bind=engine)
    return len(SQLCoursewareRepository(factory).claim_task_batch(owner, datetime.now(timezone.utc), 1))


def test_sqlite_claim_is_single_consumer_and_owner_guarded():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(
            learner_id="learner-1", learner_type="问卷学习者", education="本科", major="软件工程",
            learning_goal="测试", skill_level="初级",
        ))
        db.commit()
    repo = SQLCoursewareRepository(factory)
    repo.create_job({
        "run_id": "run-1", "learner_id": "learner-1", "request_hash": "hash-1",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-1", "run_id": "run-1", "event_type": "courseware.run",
        "idempotency_key": "task-1", "payload": {},
    })
    now = datetime.now(timezone.utc)
    assert len(repo.claim_task_batch("worker-a", now=now, limit=1)) == 1
    assert repo.claim_task_batch("worker-b", now=now, limit=1) == []
    assert repo.complete_task("task-1", "worker-b") is None
    assert repo.complete_task("task-1", "worker-a")["status"] == "complete"


def test_sqlite_file_claim_uses_cas_under_lock_and_concurrent_reentry(tmp_path):
    database_path = tmp_path / "courseware-atomic.db"
    engine = create_engine(
        f"sqlite:///{database_path.as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(
            learner_id="learner-1", learner_type="问卷学习者", education="本科", major="软件工程",
            learning_goal="测试", skill_level="初级",
        ))
        db.commit()
    repo = SQLCoursewareRepository(factory)
    repo.create_job({
        "run_id": "run-1", "learner_id": "learner-1", "request_hash": "hash-1",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-1", "run_id": "run-1", "event_type": "courseware.run",
        "idempotency_key": "task-1", "payload": {},
    })

    holder = factory()
    holder.connection().exec_driver_sql("BEGIN IMMEDIATE")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(SQLCoursewareRepository(factory).claim_task_batch, "worker-a", datetime.now(timezone.utc), 1)
        time.sleep(0.05)
        assert not future.done()
        holder.commit()
        assert len(future.result(timeout=2)) == 1
    holder.close()

    repo.enqueue_task_once({
        "outbox_id": "task-2", "run_id": "run-1", "event_type": "courseware.run",
        "idempotency_key": "task-2", "payload": {},
    })
    barrier = Barrier(2)

    def claim(owner):
        barrier.wait()
        return SQLCoursewareRepository(factory).claim_task_batch(owner, datetime.now(timezone.utc), 1)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(claim, ("worker-b", "worker-c")))
    assert sum(bool(result) for result in results) == 1


def test_expired_claim_is_reclaimable_but_live_claim_is_not():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SQLCoursewareRepository(factory)
    repo.create_job({
        "run_id": "run-expired", "learner_id": "learner-1", "request_hash": "hash-expired",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-expired", "run_id": "run-expired", "event_type": "courseware.run",
        "idempotency_key": "task-expired", "payload": {},
    })
    now = datetime.now(timezone.utc)
    first = repo.claim_task_batch("worker-a", now=now, limit=1, lease_seconds=1)
    assert len(first) == 1
    assert repo.claim_task_batch("worker-b", now=now, limit=1) == []
    reclaimed = repo.claim_task_batch("worker-b", now=now.replace(microsecond=0), limit=1)
    assert reclaimed == []  # the lease is still live
    later = now.replace(microsecond=0) + __import__("datetime").timedelta(seconds=2)
    reclaimed = repo.claim_task_batch("worker-b", now=later, limit=1)
    assert len(reclaimed) == 1
    assert reclaimed[0]["claimed_by"] == "worker-b"
    assert repo.complete_task("task-expired", "worker-a") is None
    assert repo.complete_task("task-expired", "worker-b")["status"] == "complete"


def test_sqlite_event_counter_is_atomic_for_distinct_and_duplicate_ids(tmp_path):
    engine = create_engine(
        f"sqlite:///{(tmp_path / 'events.db').as_posix()}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SQLCoursewareRepository(factory)
    repo.create_job({
        "run_id": "run-events", "learner_id": "learner-1", "request_hash": "hash-events",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    barrier = Barrier(2)

    def append(event_id):
        barrier.wait()
        return SQLCoursewareRepository(factory).append_event_once(
            "run-events", event_id, "job", "observed", {"event_id": event_id}
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        rows = list(pool.map(append, ("event-a", "event-b")))
    assert {row["event_id"] for row in rows} == {"event-a", "event-b"}
    assert {row["event_sequence"] for row in rows} == {1, 2}
    duplicate = repo.append_event_once("run-events", "event-a", "job", "changed", {})
    assert duplicate["event_sequence"] == rows[0]["event_sequence"] or duplicate["event_sequence"] == rows[1]["event_sequence"]
    assert len(repo.list_events("run-events")) == 2


def test_sqlite_independent_process_consumers_have_one_winner(tmp_path):
    database_path = tmp_path / "courseware-process.db"
    engine = create_engine(
        f"sqlite:///{database_path}",
        connect_args={"check_same_thread": False, "timeout": 5},
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    repo = SQLCoursewareRepository(factory)
    repo.create_job({
        "run_id": "run-process", "learner_id": "learner-1", "request_hash": "hash-process",
        "source_resource_ids": [], "source_snapshots": [], "status": "queued",
    })
    repo.enqueue_task_once({
        "outbox_id": "task-process", "run_id": "run-process", "event_type": "courseware.run",
        "idempotency_key": "task-process", "payload": {},
    })
    context = multiprocessing.get_context("spawn")
    with context.Pool(2) as pool:
        winners = pool.starmap(_claim_from_independent_process,
                               [(str(database_path), "process-a"), (str(database_path), "process-b")])
    assert sum(winners) == 1
