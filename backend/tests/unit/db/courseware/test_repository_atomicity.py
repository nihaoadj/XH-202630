from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.courseware.models import Base, CoursewareGenerationJobORM
from app.db.courseware.repository import MemoryCoursewareRepository, SQLCoursewareRepository
from app.db.shared.models import LearnerProfileORM


def _job(run_id: str = "run-1") -> dict:
    return {
        "run_id": run_id, "learner_id": "learner-1", "knowledge_base_id": "kb-1",
        "title": "原子操作测试", "publish_mode": "auto", "source_resource_ids": [],
        "source_snapshots": [], "request_hash": f"hash-{run_id}", "idempotency_key": f"idem-{run_id}",
        "status": "running",
    }


def _outbox(outbox_id: str = "task-1") -> dict:
    return {"outbox_id": outbox_id, "run_id": "run-1", "scene_id": None,
            "event_type": "courseware.run", "idempotency_key": f"task-idem-{outbox_id}",
            "payload": {"run_id": "run-1"}}


def _exercise(repository):
    repository.create_job(_job())
    first = repository.enqueue_task_once(_outbox())
    duplicate = repository.enqueue_task_once(_outbox())
    assert duplicate["outbox_id"] == first["outbox_id"]
    claimed = repository.claim_task_batch("worker-a", now=datetime.now(timezone.utc), limit=1)
    assert len(claimed) == 1 and claimed[0]["claimed_by"] == "worker-a"
    assert repository.renew_task_lease("task-1", "worker-b", datetime.now(timezone.utc)) is None
    assert repository.complete_task("task-1", "worker-b") is None
    failed = repository.fail_task("task-1", "worker-a", {"code": "TRANSIENT", "message": "retry"})
    assert failed["status"] == "retry"
    claimed = repository.claim_task_batch("worker-a", now=failed["next_attempt_at"] + timedelta(seconds=1), limit=1)
    assert claimed[0]["attempt"] == 2
    dead = repository.dead_letter_task("task-1", "worker-a", {"code": "FATAL", "message": "stop"})
    assert dead["status"] == "dead_lettered" and dead["last_error_code"] == "FATAL"

    checkpoint = {"checkpoint_id": "cp-1", "run_id": "run-1", "stage": "plan", "attempt": 1,
                  "state_json": {"ok": True}, "input_hash": "a" * 64, "output_hash": "b" * 64,
                  "workflow_version": "v1"}
    assert repository.save_checkpoint_once(checkpoint)["checkpoint_id"] == "cp-1"
    assert repository.save_checkpoint_once({**checkpoint, "state_json": {"changed": True}})["state_json"] == {"ok": True}
    assert repository.latest_checkpoint("run-1")["checkpoint_id"] == "cp-1"

    event = repository.append_event_once("run-1", "event-1", "planning", "started")
    assert repository.append_event_once("run-1", "event-1", "planning", "changed")["event_sequence"] == event["event_sequence"]
    assert repository.append_event_once("run-1", "event-2", "planning", "done")["event_sequence"] == event["event_sequence"] + 1

    revision = {"revision_id": "rev-1", "scene_id": "scene-1", "revision_no": 1, "trigger": "review",
                "after_content_hash": "c" * 64, "input_snapshot_hash": "d" * 64, "idempotency_key": "rev-idem"}
    assert repository.save_scene_revision_once(revision)["revision_id"] == "rev-1"
    assert repository.save_scene_revision_once({**revision, "revision_id": "rev-2"})["revision_id"] == "rev-1"

    release = {"release_id": "release-1", "run_id": "run-1", "candidate_no": 1, "status": "building",
               "release_policy": "resilient", "scene_set_hash": "e" * 64, "snapshot_set_hash": "f" * 64,
               "manifest_json": {}, "provenance_json": {}}
    assert repository.create_candidate_release_once(release)["release_id"] == "release-1"
    assert repository.create_candidate_release_once({**release, "release_id": "release-2"})["release_id"] == "release-1"
    assert repository.commit_release_once("release-1")["status"] == "released"
    assert repository.commit_release_once("release-1")["status"] == "released"


def test_memory_repository_atomic_courseware_operations():
    _exercise(MemoryCoursewareRepository())


def test_sqlite_repository_atomic_courseware_operations():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(LearnerProfileORM(
            learner_id="learner-1", learner_type="问卷学习者", education="本科", major="软件工程",
            learning_goal="测试", skill_level="初级",
        ))
        db.commit()
    _exercise(SQLCoursewareRepository(factory))


def test_sql_repository_event_sequence_uses_job_counter():
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
    repo.create_job(_job())
    assert repo.append_event({"event_id": "event-a", "run_id": "run-1", "stage": "x", "status": "ok"})["event_sequence"] == 1
    with factory() as db:
        job = db.get(CoursewareGenerationJobORM, "run-1")
        assert job.next_event_sequence == 2
