import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.audit.base import PersistenceConflict
from app.db.database import configure_sqlite_foreign_keys
from app.db.models import AgentRunORM, Base
from app.db.resource.sql_repository import SQLResourceRepository
from app.models.schemas import LearningResource


def _resource(resource_id: str, *, run_id=None):
    return LearningResource(
        resource_id=resource_id,
        learner_id="learner",
        topic="RAG",
        resource_type="讲义",
        difficulty="初级",
        content_text="content",
        knowledge_points=["retrieval"],
        source_refs=[],
        run_id=run_id,
        version=1,
    )


def _repository(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'resources.db'}")
    configure_sqlite_foreign_keys(engine)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)
    return SQLResourceRepository(factory), factory


def test_resource_repository_enforces_unique_run_type_version(tmp_path):
    repository, factory = _repository(tmp_path)
    with factory() as db:
        db.add(AgentRunORM(run_id="run-a"))
        db.commit()

    repository.save(_resource("resource-a", run_id="run-a"), "learner", "RAG", run_id="run-a")

    with pytest.raises(PersistenceConflict, match="duplicate resource version in run"):
        repository.save(
            _resource("resource-b", run_id="run-a"),
            "learner",
            "RAG",
            run_id="run-a",
        )


def test_resource_unique_guard_allows_legacy_null_run_id(tmp_path):
    repository, _ = _repository(tmp_path)

    repository.save(_resource("legacy-a"), "learner", "RAG")
    repository.save(_resource("legacy-b"), "learner", "RAG")

    assert {item.resource_id for item in repository.list_by_run(None)} == {
        "legacy-a",
        "legacy-b",
    }


def test_resource_foreign_key_error_maps_to_persistence_conflict(tmp_path):
    repository, _ = _repository(tmp_path)

    with pytest.raises(PersistenceConflict, match="resource persistence constraint conflict"):
        repository.save(
            _resource("orphan", run_id="missing-run"),
            "learner",
            "RAG",
            run_id="missing-run",
        )
