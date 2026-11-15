from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from threading import Barrier, local

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.learners.curriculum import SQLCurriculumRepository
from app.db.shared.models import (
    Base,
    KnowledgeBaseORM,
    LearnerCurriculumNodeORM,
    LearnerProfileORM,
    RagSkillNodeORM,
)


@pytest.fixture
def curriculum_database(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'curriculum.db'}",
        connect_args={"check_same_thread": False, "timeout": 15},
    )

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    with factory() as db:
        db.add(KnowledgeBaseORM(knowledge_base_id="kb", name="Test KB"))
        db.add(LearnerProfileORM(
            learner_id="learner", learner_type="student", education="test",
            major="test", learning_goal="test",
        ))
        db.flush()
        db.add_all([
            RagSkillNodeORM(node_id=node_id, knowledge_base_id="kb", name=node_id)
            for node_id in ("a", "b", "c")
        ])
        db.commit()
    yield engine, factory
    engine.dispose()


def test_concurrent_initialization_across_repositories_is_idempotent(curriculum_database):
    engine, factory = curriculum_database
    before_write = Barrier(4)
    worker = local()

    # Force all callers to reach their first INSERT together. The old read-then-
    # insert path would already have observed the same empty node collection.
    def synchronize_first_insert(_connection, _cursor, statement, _parameters, _context, _many):
        if statement.startswith("INSERT INTO learner_curriculum_nodes") and not getattr(worker, "inserted", False):
            worker.inserted = True
            before_write.wait(timeout=10)

    event.listen(engine, "before_cursor_execute", synchronize_first_insert)

    def initialize(_):
        return SQLCurriculumRepository(factory).ensure_nodes("learner", "kb", ["c", "a", "b", "a"])

    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(initialize, range(4)))
    finally:
        event.remove(engine, "before_cursor_execute", synchronize_first_insert)

    assert all([row.skill_node_id for row in rows] == ["a", "b", "c"] for rows in results)
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LearnerCurriculumNodeORM)) == 3


def test_initialization_keeps_existing_learning_progress(curriculum_database):
    _, factory = curriculum_database
    repository = SQLCurriculumRepository(factory)
    repository.ensure_nodes("learner", "kb", ["a"])
    now = datetime.now(timezone.utc)
    repository.reconcile_exposure("learner", "kb", {"a": 2}, now)
    repository.record_verification(
        "learner", "kb", attempt_id="attempt", scores={"a": 0.9}, now=now,
    )
    before = repository.list_nodes("learner", "kb")[0]

    rows = repository.ensure_nodes("learner", "kb", ["b", "a", "b"])
    after = next(row for row in rows if row.skill_node_id == "a")

    assert after == before
    assert after.progress_status.value == "completed"
    assert after.published_resource_count == 2
    assert after.verified_attempt_count == 1
    assert [row.skill_node_id for row in rows] == ["a", "b"]
    assert repository.ensure_nodes("learner", "kb", []) == rows


def test_initialization_does_not_suppress_foreign_key_errors(curriculum_database):
    _, factory = curriculum_database
    repository = SQLCurriculumRepository(factory)

    with pytest.raises(IntegrityError, match="FOREIGN KEY"):
        repository.ensure_nodes("learner", "kb", ["a", "missing-node"])

    assert repository.list_nodes("learner", "kb") == []
