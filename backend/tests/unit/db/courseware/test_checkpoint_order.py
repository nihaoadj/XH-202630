from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.courseware.models import Base, CoursewareWorkflowCheckpointORM
from app.db.courseware.repository import MemoryCoursewareRepository, SQLCoursewareRepository
from app.db.shared.models import LearnerProfileORM


@pytest.fixture(params=["memory", "sqlite"])
def repository(request, tmp_path):
    if request.param == "memory":
        repo = MemoryCoursewareRepository()
        engine = None
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'checkpoints.db'}")
        Base.metadata.create_all(engine)
        factory = sessionmaker(bind=engine)
        with factory() as db:
            db.add(LearnerProfileORM(learner_id="checkpoint-learner", learner_type="测试", education="本科",
                                     major="测试", learning_goal="验证恢复顺序", skill_level="初级"))
            db.commit()
        repo = SQLCoursewareRepository(factory)
    repo.create_job({"run_id": "checkpoint-run", "learner_id": "checkpoint-learner", "request_hash": "checkpoint-hash",
                     "source_resource_ids": [], "source_snapshots": [], "status": "running"})
    yield repo
    if engine is not None:
        engine.dispose()


def checkpoint(repo, stage, *, attempt=1, timestamp=None, identifier=None):
    identifier = identifier or f"cp-{stage}-{attempt}"
    state = {"checkpoint_id": identifier, "run_id": "checkpoint-run", "stage": stage, "attempt": attempt,
             "state_json": {"stage": stage}, "input_hash": "a" * 64, "output_hash": "b" * 64, "workflow_version": "courseware-v1"}
    result = repo.save_checkpoint_once(state)
    if timestamp is not None:
        if isinstance(repo, MemoryCoursewareRepository):
            repo.checkpoints[("checkpoint-run", stage, attempt)]["created_at"] = timestamp
        else:
            with repo.session_factory() as db:
                db.get(CoursewareWorkflowCheckpointORM, identifier).created_at = timestamp
                db.commit()
    return result, state


def test_same_timestamp_and_attempt_selects_completed_scenes(repository):
    same = datetime(2026, 10, 27, tzinfo=timezone.utc)
    checkpoint(repository, "design", timestamp=same, identifier="z-design")
    checkpoint(repository, "scenes", timestamp=same, identifier="a-scenes")
    assert repository.latest_checkpoint("checkpoint-run")["stage"] == "scenes"


def test_attempt_priority_is_preserved_before_stage_rank(repository):
    same = datetime(2026, 10, 27, tzinfo=timezone.utc)
    checkpoint(repository, "release", attempt=1, timestamp=same)
    checkpoint(repository, "design", attempt=2, timestamp=same)
    latest = repository.latest_checkpoint("checkpoint-run")
    assert latest["stage"] == "design" and latest["attempt"] == 2


def test_timestamp_priority_is_preserved_before_attempt_and_duplicate_is_immutable(repository):
    same = datetime(2026, 10, 27, tzinfo=timezone.utc)
    checkpoint(repository, "release", attempt=4, timestamp=same)
    _, state = checkpoint(repository, "snapshot", attempt=1, timestamp=same + timedelta(seconds=1))
    repository.save_checkpoint_once({**state, "state_json": {"changed": True}})
    latest = repository.latest_checkpoint("checkpoint-run")
    assert latest["stage"] == "snapshot"
    assert latest["state_json"] == {"stage": "snapshot"}


def test_unknown_historical_stages_have_matching_stable_fallback(repository):
    same = datetime(2026, 10, 27, tzinfo=timezone.utc)
    checkpoint(repository, "legacy-a", timestamp=same, identifier="a-legacy")
    checkpoint(repository, "legacy-b", timestamp=same, identifier="z-legacy")
    assert repository.latest_checkpoint("checkpoint-run")["checkpoint_id"] == "z-legacy"
